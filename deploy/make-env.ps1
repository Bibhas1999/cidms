# Writes .env.production with fresh random secrets. Run once, from the project folder:
#   powershell -File deploy\make-env.ps1 -Domain cidms.duckdns.org -Email you@gmail.com
# Keep .env.production private: it holds the database passwords. It is never committed (see .gitignore).
param(
  [Parameter(Mandatory = $true)][string]$Domain,
  [Parameter(Mandatory = $true)][string]$Email
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$out = Join-Path $root ".env.production"
if (Test-Path $out) { throw ".env.production already exists. Delete it first if you really want new secrets (the database keeps the old ones)." }

function New-Secret([int]$bytes = 32) {
  $b = New-Object byte[] $bytes
  [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($b)
  # URL-safe, no characters that need escaping in a database URL
  return ([Convert]::ToBase64String($b)).TrimEnd("=").Replace("+", "A").Replace("/", "B")
}
$owner = New-Secret; $app = New-Secret; $session = New-Secret 48

$text = Get-Content (Join-Path $PSScriptRoot "env.production.example") -Raw
$text = $text.Replace("BASE_DOMAIN=cidms.duckdns.org", "BASE_DOMAIN=$Domain")
$text = $text.Replace("ACME_EMAIL=you@example.com", "ACME_EMAIL=$Email")
$text = $text.Replace("POSTGRES_OWNER_PASSWORD=__RANDOM__", "POSTGRES_OWNER_PASSWORD=$owner")
$text = $text.Replace("POSTGRES_APP_PASSWORD=__RANDOM__", "POSTGRES_APP_PASSWORD=$app")
$text = $text.Replace("__APP_PASSWORD__", $app).Replace("__OWNER_PASSWORD__", $owner)
$text = $text.Replace("SESSION_SECRET=__RANDOM__", "SESSION_SECRET=$session")
[System.IO.File]::WriteAllText($out, $text, (New-Object System.Text.UTF8Encoding $false))
Write-Host "Wrote $out (secrets generated). Keep it private."
