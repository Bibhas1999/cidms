// Parts of the product that are built (or being built) but not shown yet. Turning one on brings back
// its pages, menu items and links everywhere at once.
//
//   testReports: medical test reports — the report editor, DICOM image viewer, WhatsApp sending, the
//                patient QR link and the "My signature" settings. On hold at the owner's request
//                (11 Oct 2026): the app is billing only for now. The server side stays in place.

//   worklist:    the lab Worklist page. Off: each test's report is marked Pending / Ready / Delivered on
//                its bill instead (owner's request, 11 Oct 2026).

export const FEATURES = {
  testReports: false,
  worklist: false,
} as const;
