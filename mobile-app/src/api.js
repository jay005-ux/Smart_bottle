import axios from "axios";
import Constants from "expo-constants";

const configuredUrl =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  Constants.expoConfig?.extra?.apiBaseUrl ||
  "http://192.168.18.73:8000/api/";

export const API_BASE_URL = configuredUrl.endsWith("/")
  ? configuredUrl
  : `${configuredUrl}/`;

export default axios.create({
  baseURL: API_BASE_URL,
  timeout: 8000,
});
