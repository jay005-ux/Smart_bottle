const appJson = require("./app.json");

const apiBaseUrl =
  process.env.EXPO_PUBLIC_API_BASE_URL ||
  appJson.expo.extra?.apiBaseUrl ||
  "http://54.174.213.77:8000/api/";

module.exports = {
  expo: {
    ...appJson.expo,
    extra: {
      ...(appJson.expo.extra || {}),
      apiBaseUrl,
    },
  },
};
