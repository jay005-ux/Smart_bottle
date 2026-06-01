import axios from "axios";

export const API_BASE_URL =
  process.env.REACT_APP_API_BASE_URL || "http://192.168.18.73:8000/api/";

export default axios.create({
  baseURL: API_BASE_URL,
  timeout: 10000,
});
