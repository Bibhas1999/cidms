// Parts of the product that are built (or being built) but not shown yet. Turning one on brings back
// its pages, menu items and links everywhere at once.
//
//   testReports: medical test reports — the report editor (typed or an uploaded PDF), DICOM image viewer, WhatsApp sending, the
//                patient QR link and the "My signature" settings. Was off 11 - 30 Oct 2026 (app billing-only
//                for that stretch, at the owner's request); back on by the owner's request. Also brings the
//                /test-reports dashboard and list into the menu.

//   worklist:    the lab Worklist page (shown in the menu as "Investigation Report"): a simpler Pending /
//                Scanned / Delivered tracker, the alternative to testReports rather than something used
//                alongside it. Off (31 Oct 2026, owner's request): testReports is the one in use.

//   typedReports: within testReports, starting a report by typing it (template or blank, then Findings /
//                 Impression). Off (31 Oct 2026, owner's request): for now a report can only be an uploaded
//                 PDF - the "Write report" card doesn't show. Doesn't affect a report someone already typed.

export const FEATURES = {
  testReports: true,
  worklist: false,
  typedReports: false,
} as const;
