// The extraction schema: the LLM produces this, the coach reviews it, and the
// deterministic generator consumes it. splitCount / ordering / discrepancies
// are computed in code — never by the LLM.

export type Course = "long" | "short";

export interface MeetInfo {
  name: string;
  venue: string;
  dates: string;
  course: Course;
  club: string;
}

export interface SessionInfo {
  timelineTag: string; // "t1".."t4"
  day: string; // e.g. "Sunday 31 May"
  ampm: string; // "AM" | "PM" | ""
  label: string; // e.g. "Session 3"
}

export interface Swimmer {
  first: string;
  surname: string;
  age: number | null;
  entryTime: string; // "1:29.60", "36.50", or "NT"
}

export interface EventEntry {
  number: number;
  timelineTag: string;
  gender: string; // "Girls" | "Boys"
  distanceM: number;
  stroke: string; // "Back" | "Breast" | "Free" | "Fly" | "IM" | "Medley"
  swimmers: Swimmer[];
}

export interface Attendance {
  provided: boolean;
  bySession: { timelineTag: string; swimmers: string[] }[];
}

export interface Extraction {
  meet: MeetInfo;
  sessions: SessionInfo[];
  events: EventEntry[];
  attendance: Attendance;
  extractionNotes: string[];
}

// What a saved pack stores so it can be regenerated deterministically.
export interface PackSource {
  meet: MeetInfo;
  poolLengthM: number;
  sessionNumber: number;
  sessionLabel: string; // e.g. "Sunday 31 May AM"
  timelineTag: string;
  events: EventEntry[]; // only the selected session's events
  attendance: Attendance;
}

// JSON Schema for Claude structured outputs. Constraints: every object needs
// additionalProperties:false; no numeric min/max; no recursion.
export const EXTRACTION_JSON_SCHEMA = {
  type: "object",
  additionalProperties: false,
  required: ["meet", "sessions", "events", "attendance", "extractionNotes"],
  properties: {
    meet: {
      type: "object",
      additionalProperties: false,
      required: ["name", "venue", "dates", "course", "club"],
      properties: {
        name: { type: "string" },
        venue: { type: "string" },
        dates: { type: "string" },
        course: { type: "string", enum: ["long", "short"] },
        club: { type: "string" },
      },
    },
    sessions: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["timelineTag", "day", "ampm", "label"],
        properties: {
          timelineTag: { type: "string" },
          day: { type: "string" },
          ampm: { type: "string", enum: ["AM", "PM", ""] },
          label: { type: "string" },
        },
      },
    },
    events: {
      type: "array",
      items: {
        type: "object",
        additionalProperties: false,
        required: ["number", "timelineTag", "gender", "distanceM", "stroke", "swimmers"],
        properties: {
          number: { type: "integer" },
          timelineTag: { type: "string" },
          gender: { type: "string", enum: ["Girls", "Boys"] },
          distanceM: { type: "integer" },
          stroke: { type: "string", enum: ["Back", "Breast", "Free", "Fly", "IM", "Medley"] },
          swimmers: {
            type: "array",
            items: {
              type: "object",
              additionalProperties: false,
              required: ["first", "surname", "age", "entryTime"],
              properties: {
                first: { type: "string" },
                surname: { type: "string" },
                age: { type: ["integer", "null"] },
                entryTime: { type: "string" },
              },
            },
          },
        },
      },
    },
    attendance: {
      type: "object",
      additionalProperties: false,
      required: ["provided", "bySession"],
      properties: {
        provided: { type: "boolean" },
        bySession: {
          type: "array",
          items: {
            type: "object",
            additionalProperties: false,
            required: ["timelineTag", "swimmers"],
            properties: {
              timelineTag: { type: "string" },
              swimmers: { type: "array", items: { type: "string" } },
            },
          },
        },
      },
    },
    extractionNotes: { type: "array", items: { type: "string" } },
  },
} as const;
