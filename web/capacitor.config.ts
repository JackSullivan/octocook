import type { CapacitorConfig } from '@capacitor/cli'

// Live-reload mode: set CAPACITOR_DEV_SERVER_URL to the LAN URL of the
// Vite dev server (e.g. http://192.168.0.196:5173). The Android app then
// loads its UI from that URL and picks up code changes as you save.
//
// Production-ish mode: leave the env var unset and the app loads the
// bundled web/dist/ assets (produced by `npm run build`).
const devUrl = process.env.CAPACITOR_DEV_SERVER_URL

const config: CapacitorConfig = {
  appId: 'com.octocook.app',
  appName: 'Octocook',
  webDir: 'dist',
  server: devUrl
    ? {
        url: devUrl,
        cleartext: true,
        androidScheme: 'http',
      }
    : {
        androidScheme: 'http',
        cleartext: true,
      },
}

export default config
