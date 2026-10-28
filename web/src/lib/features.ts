// Parts of the product that are built (or being built) but not shown yet. Turning one on brings back
// its pages, menu items and links everywhere at once.
//
//   testReports: medical test reports — the report editor (typed or an uploaded PDF), DICOM image viewer, WhatsApp sending, the
//                patient QR link and the "My signature" settings. On hold at the owner's request
//                (11 Oct 2026; confirmed 18 Oct): the app is billing only for now. Everything stays built and tested;
//                turning this on also brings the /test-reports dashboard and list into the menu.

// The lab Worklist is always on now: it's each department's own screen (work areas, lib/area.svelte.ts). Reception
// still marks tests Pending / Ready / Delivered on the bill as well.

export const FEATURES = {
  testReports: false,
} as const;
