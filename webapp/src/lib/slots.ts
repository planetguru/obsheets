// Upload slot definitions, shared by the wizard UI and the extraction API.
// Pure data — safe to import from client components.
export const DOC_SLOTS = [
  {
    key: "entries",
    label: "Confirmed entries report",
    sublabel: "Hy-Tek “Entries – All Events” PDF",
    required: true,
    purpose: "The definitive list of who swims what, with entry times. This document wins any conflict.",
  },
  {
    key: "committed",
    label: "Committed athletes export",
    sublabel: "HTML or PDF from your club system",
    required: false,
    purpose: "Maps each event to a session via its (d1/t1)-style tag.",
  },
  {
    key: "meetPack",
    label: "Meet pack",
    sublabel: "The promoter's information PDF",
    required: false,
    purpose: "Meet name, venue, dates, and long vs short course.",
  },
  {
    key: "attendance",
    label: "TM session attendance list",
    sublabel: "Team manager's PDF",
    required: false,
    purpose: "Used only to flag discrepancies — it never changes the sheet.",
  },
] as const;

export type SlotKey = (typeof DOC_SLOTS)[number]["key"];
