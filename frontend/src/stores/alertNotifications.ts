import { create } from "zustand";
import type { components } from "../api/types";

export type AlertEventOut = components["schemas"]["AlertEventOut"];
export type AlertOut = components["schemas"]["AlertOut"];

/** A toast entry pairs the trigger event with the alert that produced
 *  it so the toast component can style by `alert.repeat_mode` (one_shot
 *  → red border, recurring → yellow). `bornAt` is the client clock at
 *  push time and drives the 5s auto-dismiss timer. */
export interface AlertToast {
  event: AlertEventOut;
  alert: AlertOut;
  bornAt: number;
}

const HISTORY_CAP = 100;
const TOAST_CAP = 3;

interface AlertNotificationsState {
  /** Count of unread alert events since last clearUnread(). */
  unreadCount: number;

  /** Full history of received alert events (newest first, capped at 100). */
  history: AlertEventOut[];

  /** Currently visible toast queue (max 3). Newest at the front. */
  activeToasts: AlertToast[];

  /** Ingest a new alert event + its alert: increments unread, prepends
   *  to history, and adds to the active toast queue. */
  push(event: AlertEventOut, alert: AlertOut): void;

  /** Mark all events as read (reset unread counter). */
  clearUnread(): void;

  /** Dismiss a toast by event id. */
  dismissToast(eventId: number): void;

  /** Clear the history list. */
  clearHistory(): void;
}

export const useAlertNotificationsStore = create<AlertNotificationsState>((set) => ({
  unreadCount: 0,
  history: [],
  activeToasts: [],

  push: (event, alert) =>
    set((state) => {
      const history = [event, ...state.history].slice(0, HISTORY_CAP);
      const toast: AlertToast = { event, alert, bornAt: Date.now() };
      const activeToasts = [toast, ...state.activeToasts].slice(0, TOAST_CAP);
      return {
        unreadCount: state.unreadCount + 1,
        history,
        activeToasts,
      };
    }),

  clearUnread: () => set({ unreadCount: 0 }),

  dismissToast: (eventId) =>
    set((state) => ({
      activeToasts: state.activeToasts.filter((t) => t.event.id !== eventId),
    })),

  clearHistory: () => set({ history: [] }),
}));
