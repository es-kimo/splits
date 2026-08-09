export interface AthleteHistoryItem {
  year: number | null;
  age: number | null;
  meet: string;
  distance: number | null;
  sf: boolean;
  rank: number;
  round: string;
}

export interface AthleteElemSummary {
  best: number | null;
  median: number | null;
  worst: number | null;
  count: number;
}

export interface Athlete {
  idNo: string;
  slug: string;
  url: string;
  name: string;
  birth: number | null;
  team: string;
  gender: string | null;
  designationReason: string;
  mediaReportUrl: string;
  designatedAt: string;
  status: "active" | "removed";
  first: number | null;
  ages: Record<string, number | null>;
  elem: AthleteElemSummary;
  history: AthleteHistoryItem[];
}

export interface AthletesDoc {
  ages: number[];
  athletes: Athlete[];
}

export interface MeetItem {
  year: number;
  meet: string;
  raceCount: number;
  athleteCount: number;
  distanceSet: number[];
  roundTypes: string[];
  hasSemifinal: boolean;
}

export interface MeetsDoc {
  items: MeetItem[];
}

export interface PeerDistributionFilters {
  birthYears: number[];
  genders: string[];
  schoolLevels: string[];
  distances: number[];
}

export interface PeerDistributionRow {
  birthYear: number;
  gender: string;
  schoolLevel: string;
  distance: number;
  athleteCount: number | null;
  insufficient: boolean;
  timeP10: number | null;
  timeP25: number | null;
  timeP50: number | null;
  timeP75: number | null;
  timeP90: number | null;
  rankP25: number | null;
  rankP50: number | null;
  rankP75: number | null;
}

export interface DistributionDoc {
  kAnonymityMin: number;
  insufficientText: string;
  filters: PeerDistributionFilters;
  rows: PeerDistributionRow[];
}

export interface MetaDoc {
  athleteCount: number;
  placementCount: number;
  yearStart: number | null;
  yearEnd: number | null;
  yearSpan: number | null;
  ageMin: number | null;
  ageMax: number | null;
  elemTop2Count: number;
  elemWorstBand: string;
  firstAgeMin: number | null;
  firstAgeMax: number | null;
  missingElemNames: string[];
  generatedAt: string;
  publicFigureCount: number;
  activeFigureCount: number;
}
