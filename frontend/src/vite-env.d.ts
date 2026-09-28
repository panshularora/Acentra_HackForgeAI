/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Optional absolute origin for REST calls; defaults to same-origin. */
  readonly VITE_API_BASE?: string;
  /** Optional absolute WebSocket URL; defaults to ws(s)://<page host>/ws. */
  readonly VITE_WS_URL?: string;
}
