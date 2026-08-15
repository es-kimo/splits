export interface AthleteHistoryItem {
  year: number | null;
  age: number | null;
  meet: string;
  meetSlug: string | null;
  meetUrl: string | null;
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
  slug: string;
  url: string;
  raceCount: number;
  athleteCount: number;
  distanceSet: number[];
  roundTypes: string[];
  hasSemifinal: boolean;
  dateStart: string | null;
  dateEnd: string | null;
  location: string | null;
  categoryBreakdown: MeetCategoryBreakdownItem[];
  distanceDistribution: MeetDistanceDistribution;
  publicFigureResults: MeetPublicFigureResult[];
  seriesKey: string;
  seriesName: string;
  seriesRound: number | null;
  seriesLinks: MeetSeriesLink[];
}

export interface MeetsDoc {
  items: MeetItem[];
}

export interface MeetCategoryBreakdownItem {
  category: string;
  athleteCount: number;
}

export interface MeetDistanceDistributionItem {
  distance: number;
  athleteCount: number | null;
  insufficient: boolean;
  timeP10: number | null;
  timeP25: number | null;
  timeP50: number | null;
  timeP75: number | null;
  timeP90: number | null;
}

export interface MeetDistanceDistribution {
  kAnonymityMin: number;
  insufficientText: string;
  items: MeetDistanceDistributionItem[];
}

export interface MeetPublicFigurePlacement {
  distance: number | null;
  rank: number;
  sf: boolean;
  round: string;
}

export interface MeetPublicFigureResult {
  name: string;
  slug: string;
  url: string;
  bestRank: number;
  raceCount: number;
  distances: number[];
  rounds: string[];
  placements: MeetPublicFigurePlacement[];
}

export interface MeetSeriesLink {
  year: number;
  meet: string;
  slug: string;
  url: string;
}

export interface PeerDistributionFilters {
  birthYears: number[];
  genders: string[];
  distances: number[];
}

export interface PeerDistributionRow {
  birthYear: number;
  gender: string;
  distance: number;
  timeCount: number | null;
  timeInsufficient: boolean;
  rankCount: number | null;
  rankInsufficient: boolean;
  timeP05: number | null;
  timeP10: number | null;
  timeP20: number | null;
  timeP30: number | null;
  timeP40: number | null;
  timeP50: number | null;
  timeP60: number | null;
  timeP70: number | null;
  timeP80: number | null;
  timeP90: number | null;
  timeP95: number | null;
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
