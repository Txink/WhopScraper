// frontend/src/api/domain-types.ts
// Re-exports common schema types under shorter names for ergonomic DX.
// Auto-derived from openapi-typescript output — regenerate via: npm run gen:types
import type { components } from "./types";

export type Task = components["schemas"]["TaskOut"];
export type TaskSummary = components["schemas"]["TaskSummaryOut"];
export type TaskList = components["schemas"]["TaskListOut"];
export type Message = components["schemas"]["MessageOut"];
export type Instruction = components["schemas"]["InstructionOut"];
export type PushEvent = components["schemas"]["PushEventOut"];
export type Position = components["schemas"]["PositionOut"];
export type Positions = components["schemas"]["PositionsOut"];
export type StatsToday = components["schemas"]["StatsTodayOut"];
export type Health = components["schemas"]["HealthOut"];

export type BrokerStatus = components["schemas"]["BrokerStatusOut"];

export type WhopPage = components["schemas"]["WhopPageOut"];
export type WhopPages = components["schemas"]["WhopPagesOut"];
export type WhopPageCreate = components["schemas"]["WhopPageCreate"];
export type WhopCookieStatus = components["schemas"]["WhopCookieStatusOut"];
export type WhopPageSettings = components["schemas"]["WhopPageSettingsOut"];
export type WhopPageSettingsPatch = components["schemas"]["WhopPageSettingsPatch"];
export type TickerConfig = components["schemas"]["TickerConfigOut"];

export interface LongportCredentialSet {
  app_key: string;
  app_secret: string;
  access_token: string;
}

export interface LongportSettings {
  mode: "paper" | "real";
  paper: LongportCredentialSet;
  real: LongportCredentialSet;
  auto_trade: boolean;
  region: string;
  dry_run: boolean;
}

export interface LongportSettingsPatch {
  mode?: "paper" | "real";
  paper?: LongportCredentialSet;
  real?: LongportCredentialSet;
  auto_trade?: boolean;
  region?: string;
  dry_run?: boolean;
}
