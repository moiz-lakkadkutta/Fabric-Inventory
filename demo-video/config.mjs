// Throwaway local stack only (see prepare.sh). The password is the seed
// CLI's public dev default, never used on a real deployment.
export const APP = process.env.VIDEO_APP_URL ?? 'http://localhost:5173';
export const API = process.env.VIDEO_API_URL ?? 'http://localhost:8000';
export const LOGIN = {
  email: 'demo@fabric-demo.in',
  password: 'DemoPass123',
  org_name: 'Fabric Demo Textiles',
};
export const FIRM = 'Noor Suits Pvt Ltd';
export const VOICE = process.env.VIDEO_VOICE ?? 'Rishi';
// The page lays out at 1440×810 CSS px (larger, readable text) and the
// screencast captures at that size; ffmpeg upscales the take to 1080p.
export const VIEWPORT = { width: 1440, height: 810 };
export const SCALE = 1;
export const VIDEO = { width: 1920, height: 1080 };
export const SPEECH_RATE = Number(process.env.VIDEO_RATE ?? 172); // words per minute
