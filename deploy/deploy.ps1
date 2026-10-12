# Deploys CIDMS from this computer to the server, over SSH. From the project folder:
#   powershell -File deploy\deploy.ps1 -Ip 140.238.x.x -Key $HOME\.ssh\ssh-key-2026-10-12.key            # update
#   powershell -File deploy\deploy.ps1 -Ip 140.238.x.x -Key $HOME\.ssh\ssh-key-2026-10-12.key -FirstTime  # + server set-up
#   ... -MoveData   also copies this computer's database to the server (first time only: replaces the server's data)
param(
  [Parameter(Mandatory = $true)][string]$Ip,
  [Parameter(Mandatory = $true)][string]$Key,
  [string]$User = "opc",        # Oracle Linux: opc; Ubuntu: ubuntu
  [switch]$FirstTime,
  [switch]$MoveData
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
if (-not (Test-Path ".env.production")) { throw "Make .env.production first: powershell -File deploy\make-env.ps1 -Domain ... -Email ..." }
$target = "$User@$Ip"
$ssh = @("-i", $Key, "-o", "StrictHostKeyChecking=accept-new", "-o", "ServerAliveInterval=30")
function Remote([string]$cmd) { & ssh @ssh $target $cmd; if ($LASTEXITCODE) { throw "failed on the server: $cmd" } }

Write-Host "== packing the app"
$pack = Join-Path $env:TEMP "supreme-dms.tgz"
tar -czf $pack --exclude=./web/node_modules --exclude=./.venv --exclude=./storage --exclude=./web/dist --exclude=./.git `
    --exclude="*/__pycache__" --exclude=./.env --exclude=./.env.production --exclude=./backups .
& scp @ssh $pack "${target}:/tmp/supreme-dms.tgz"; if ($LASTEXITCODE) { throw "copy failed" }
& scp @ssh ".env.production" "${target}:/tmp/.env.production"; if ($LASTEXITCODE) { throw "copy failed" }

if ($FirstTime) {
  Write-Host "== setting the server up (Docker, firewall, swap, backups)"
  & scp @ssh "deploy\server-setup.sh" "${target}:/tmp/server-setup.sh"
  Remote "sudo bash /tmp/server-setup.sh"
}

Write-Host "== unpacking"
Remote "mkdir -p /opt/supreme-dms && cd /opt/supreme-dms && tar -xzf /tmp/supreme-dms.tgz && mv /tmp/.env.production .env.production && chmod 600 .env.production && chmod +x deploy/*.sh && rm /tmp/supreme-dms.tgz"
$compose = "cd /opt/supreme-dms && sudo docker compose -f deploy/docker-compose.prod.yml --env-file .env.production"

if ($MoveData) {
  Write-Host "== copying this computer's database to the server"
  $dump = Join-Path $env:TEMP "supreme-local.dump"
  docker exec supreme_dms-postgres-1 pg_dump -U supreme_owner -d supreme --format=custom --compress=9 -f /tmp/supreme-local.dump
  docker cp supreme_dms-postgres-1:/tmp/supreme-local.dump $dump
  & scp @ssh $dump "${target}:/opt/supreme-dms/backups/supreme-local.dump"
  Remote "$compose up -d postgres && sleep 8 && $compose exec -T postgres pg_restore -U supreme_owner -d supreme --clean --if-exists --no-owner --role=supreme_owner --single-transaction < backups/supreme-local.dump"
}

Write-Host "== building and starting (the first build takes a few minutes)"
Remote "$compose up -d --build"
Remote "sleep 10 && $compose ps"
Write-Host "== checking over HTTPS"
$domain = ((Get-Content ".env.production" | Select-String '^BASE_DOMAIN=').Line -split "=", 2)[1].Trim()
foreach ($u in "https://admin.$domain/readyz") {
  $ok = $false
  for ($i = 0; $i -lt 12 -and -not $ok; $i++) {
    try { $r = Invoke-WebRequest -UseBasicParsing -TimeoutSec 30 $u; $ok = $r.StatusCode -eq 200; Write-Host "$u -> $($r.Content)" }
    catch { Start-Sleep -Seconds 5 }
  }
  if (-not $ok) { Write-Host "Not answering yet: $u. Logs:"; Remote "$compose logs --tail=30 app caddy" }
}
Write-Host "Done. Open https://<centre>.$domain (the first visit to each address gets its certificate: allow 10-20 seconds)."
