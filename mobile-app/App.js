import React, { useCallback, useEffect, useMemo, useState } from "react";
import {
  ActivityIndicator,
  Alert,
  AppState,
  Pressable,
  ScrollView,
  StyleSheet,
  Text,
  TextInput,
  View,
} from "react-native";
import { Ionicons } from "@expo/vector-icons";
import { CameraView, useCameraPermissions } from "expo-camera";
import * as BackgroundTask from "expo-background-task";
import * as Device from "expo-device";
import * as Notifications from "expo-notifications";
import { StatusBar } from "expo-status-bar";
import * as SecureStore from "expo-secure-store";
import * as TaskManager from "expo-task-manager";
import {
  SafeAreaProvider,
  SafeAreaView,
  useSafeAreaInsets,
} from "react-native-safe-area-context";

import API, { API_BASE_URL } from "./src/api";

const TOKEN_KEY = "smart_bottle_parent_token";
const BACKGROUND_SYNC_TASK = "smart-bottle-background-sync";
const LAST_SYNC_KEY = "smart_bottle_last_background_sync";
const APP_POLL_INTERVAL_MS = 15000;

Notifications.setNotificationHandler({
  handleNotification: async () => ({
    shouldShowAlert: true,
    shouldPlaySound: true,
    shouldSetBadge: false,
    shouldShowBanner: true,
    shouldShowList: true,
  }),
});

function formatMl(value) {
  const numberValue = Number(value || 0);
  return `${numberValue.toFixed(0)} ml`;
}

function formatTime(value) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue) || numberValue <= 0) {
    return "--";
  }
  return new Date(numberValue * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDateTime(value) {
  if (!value) {
    return "--";
  }

  return new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatSyncTime(value) {
  if (!value) {
    return "Not synced yet";
  }

  return `Last sync ${new Date(value).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  })}`;
}

function parsePairingData(value) {
  if (!value) {
    return null;
  }

  try {
    const parsed = JSON.parse(value);
    if (parsed.device_id && parsed.pairing_token) {
      return {
        device_id: parsed.device_id,
        pairing_token: parsed.pairing_token,
      };
    }
  } catch {}

  try {
    const url = new URL(value);
    const deviceId = url.searchParams.get("device_id");
    const token = url.searchParams.get("token") || url.searchParams.get("pairing_token");

    if (deviceId && token) {
      return {
        device_id: deviceId,
        pairing_token: token,
      };
    }
  } catch {}

  return null;
}

async function getExpoPushToken() {
  if (!Device.isDevice) {
    throw new Error("Push notifications require a real phone.");
  }

  await Notifications.setNotificationChannelAsync("hydration-alerts", {
    name: "Hydration alerts",
    importance: Notifications.AndroidImportance.HIGH,
    sound: "default",
  });

  const current = await Notifications.getPermissionsAsync();
  let finalStatus = current.status;

  if (current.status !== "granted") {
    const requested = await Notifications.requestPermissionsAsync();
    finalStatus = requested.status;
  }

  if (finalStatus !== "granted") {
    throw new Error("Notification permission was not granted.");
  }

  const tokenResult = await Notifications.getExpoPushTokenAsync();
  return tokenResult.data;
}

async function runBackgroundDataLoad() {
  const savedToken = await SecureStore.getItemAsync(TOKEN_KEY);
  if (!savedToken) {
    return false;
  }

  const headers = {
    Authorization: `Token ${savedToken}`,
  };

  const devicesRes = await fetch(`${API_BASE_URL}devices/`, { headers });
  const childrenRes = await fetch(`${API_BASE_URL}children/`, { headers });
  const notificationsRes = await fetch(`${API_BASE_URL}notifications/`, { headers });
  const reportsRes = await fetch(`${API_BASE_URL}reports/`, { headers });

  if (!devicesRes.ok || !childrenRes.ok || !notificationsRes.ok || !reportsRes.ok) {
    return false;
  }

  const devices = await devicesRes.json();
  const firstDeviceId = devices?.[0]?.device_id;

  if (firstDeviceId) {
    await Promise.all([
      fetch(`${API_BASE_URL}data/?device_id=${encodeURIComponent(firstDeviceId)}`, { headers }),
      fetch(`${API_BASE_URL}daily-15/?device_id=${encodeURIComponent(firstDeviceId)}`, { headers }),
    ]);
  }

  await SecureStore.setItemAsync(LAST_SYNC_KEY, new Date().toISOString());
  return true;
}

TaskManager.defineTask(BACKGROUND_SYNC_TASK, async () => {
  try {
    const synced = await runBackgroundDataLoad();
    return synced
      ? BackgroundTask.BackgroundTaskResult.Success
      : BackgroundTask.BackgroundTaskResult.Failed;
  } catch {
    return BackgroundTask.BackgroundTaskResult.Failed;
  }
});

function AppContent() {
  const insets = useSafeAreaInsets();
  const [permission, requestPermission] = useCameraPermissions();
  const [token, setToken] = useState("");
  const [parent, setParent] = useState(null);
  const [activeMenu, setActiveMenu] = useState("home");
  const [authMode, setAuthMode] = useState("login");
  const [authForm, setAuthForm] = useState({
    username: "",
    email: "",
    phone: "",
    password: "",
  });
  const [rows, setRows] = useState([]);
  const [days, setDays] = useState([]);
  const [devices, setDevices] = useState([]);
  const [children, setChildren] = useState([]);
  const [notifications, setNotifications] = useState([]);
  const [reports, setReports] = useState([]);
  const [pushStatus, setPushStatus] = useState("Not registered");
  const [syncStatus, setSyncStatus] = useState("Background sync not enabled");
  const [notificationSettings, setNotificationSettings] = useState(null);
  const [profileForm, setProfileForm] = useState({ email: "", phone: "" });
  const [passwordForm, setPasswordForm] = useState({ current_password: "", new_password: "" });
  const [childForm, setChildForm] = useState({
    name: "",
    age: "",
    weight_kg: "",
    activity_level: "normal",
    heat_sensitivity: false,
    school_name: "",
    school_start: "08:00",
    school_end: "15:00",
    school_mode_enabled: true,
    daily_goal_ml: "",
  });
  const [selectedChildId, setSelectedChildId] = useState(null);
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [restoringSession, setRestoringSession] = useState(true);
  const [pairing, setPairing] = useState({
    child_name: "",
    age: "",
    school_name: "",
    device_id: "",
    pairing_token: "",
  });
  const [scannerOpen, setScannerOpen] = useState(false);
  const [scanned, setScanned] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  const latest = rows[0] || null;
  const selectedChild = children.find((child) => child.id === selectedChildId) || children[0] || null;
  const devicesForSelectedChild = selectedChild
    ? devices.filter((device) => device.child === selectedChild.id)
    : devices;
  const visibleDevices = devicesForSelectedChild.length ? devicesForSelectedChild : devices;
  const selectedDevice =
    visibleDevices.find((device) => device.device_id === selectedDeviceId) ||
    visibleDevices[0] ||
    null;
  const selectedReport =
    reports.find((report) => report.device?.device_id === selectedDevice?.device_id) ||
    reports[0] ||
    null;

  useEffect(() => {
    if (parent) {
      setProfileForm({
        email: parent.email || "",
        phone: parent.phone || "",
      });
    }
  }, [parent]);

  useEffect(() => {
    if (selectedChild) {
      setChildForm({
        name: selectedChild.name || "",
        age: selectedChild.age ? String(selectedChild.age) : "",
        weight_kg: selectedChild.weight_kg ? String(selectedChild.weight_kg) : "",
        activity_level: selectedChild.activity_level || "normal",
        heat_sensitivity: Boolean(selectedChild.heat_sensitivity),
        school_name: selectedChild.school_name || "",
        school_start: selectedChild.school_start || "08:00",
        school_end: selectedChild.school_end || "15:00",
        school_mode_enabled: selectedChild.school_mode_enabled !== false,
        daily_goal_ml: selectedChild.daily_goal_ml ? String(selectedChild.daily_goal_ml) : "4000",
      });
    }
  }, [selectedChild?.id]);

  useEffect(() => {
    if (token) {
      API.defaults.headers.common.Authorization = `Token ${token}`;
    } else {
      delete API.defaults.headers.common.Authorization;
    }
  }, [token]);

  const refreshLastSyncStatus = useCallback(async (backgroundEnabled = false) => {
    const lastSync = await SecureStore.getItemAsync(LAST_SYNC_KEY);
    const label = formatSyncTime(lastSync);
    setSyncStatus(
      backgroundEnabled && label !== "Not synced yet"
        ? `${label} | background enabled`
        : backgroundEnabled
          ? "Background sync enabled"
          : label
    );
  }, []);

  const registerBackgroundSync = useCallback(async () => {
    try {
      const status = await BackgroundTask.getStatusAsync();

      if (status !== BackgroundTask.BackgroundTaskStatus.Available) {
        setSyncStatus("Background sync unavailable on this device");
        return;
      }

      const registered = await TaskManager.isTaskRegisteredAsync(BACKGROUND_SYNC_TASK);
      if (!registered) {
        await BackgroundTask.registerTaskAsync(BACKGROUND_SYNC_TASK, {
          minimumInterval: 15,
        });
      }

      await refreshLastSyncStatus(true);
    } catch {
      setSyncStatus("Background sync setup failed");
    }
  }, [refreshLastSyncStatus]);

  useEffect(() => {
    let mounted = true;

    async function restoreSession() {
      try {
        const savedToken = await SecureStore.getItemAsync(TOKEN_KEY);

        if (!savedToken || !mounted) {
          return;
        }

        API.defaults.headers.common.Authorization = `Token ${savedToken}`;
        const res = await API.get("auth/me/");

        if (mounted) {
          setToken(savedToken);
          setParent(res.data);
        }
      } catch {
        await SecureStore.deleteItemAsync(TOKEN_KEY);
      } finally {
        if (mounted) {
          setRestoringSession(false);
        }
      }
    }

    restoreSession();
    return () => {
      mounted = false;
    };
  }, []);

  const loadData = useCallback(async (options = {}) => {
    if (!token) {
      return;
    }

    const silent = Boolean(options.silent);

    if (!silent) {
      setLoading(true);
    }

    try {
      const [devicesRes, childrenRes, notificationsRes, settingsRes, reportsRes] = await Promise.all([
        API.get("devices/"),
        API.get("children/"),
        API.get("notifications/"),
        API.get("notification-settings/"),
        API.get("reports/"),
      ]);

      const nextDevices = devicesRes.data || [];
      const nextChildren = childrenRes.data || [];
      const childStillExists = nextChildren.some((child) => child.id === selectedChildId);
      const nextChildId = childStillExists ? selectedChildId : nextChildren[0]?.id || null;
      const devicesForChild = nextChildId
        ? nextDevices.filter((device) => device.child === nextChildId)
        : nextDevices;
      const candidateDevices = devicesForChild.length ? devicesForChild : nextDevices;
      const deviceStillExists = candidateDevices.some(
        (device) => device.device_id === selectedDeviceId
      );
      const deviceId = deviceStillExists
        ? selectedDeviceId
        : candidateDevices[0]?.device_id || "";

      setDevices(nextDevices);
      setChildren(nextChildren);
      setNotifications(notificationsRes.data || []);
      setReports(reportsRes.data?.reports || []);
      setNotificationSettings(settingsRes.data || null);
      setSelectedChildId(nextChildId);
      setSelectedDeviceId(deviceId);

      if (deviceId) {
        const [dataRes, daysRes] = await Promise.all([
          API.get(`data/?device_id=${deviceId}`),
          API.get(`daily-15/?device_id=${deviceId}`),
        ]);
        setRows(dataRes.data || []);
        setDays(daysRes.data || []);
      } else {
        setRows([]);
        setDays([]);
      }

      setError("");
      await SecureStore.setItemAsync(LAST_SYNC_KEY, new Date().toISOString());
      await refreshLastSyncStatus();
    } catch (e) {
      if (!silent) {
        setError("Unable to load parent bottle data");
      }
    } finally {
      if (!silent) {
        setLoading(false);
      }
    }
  }, [token, selectedChildId, selectedDeviceId, refreshLastSyncStatus]);

  useEffect(() => {
    loadData();
    const timer = setInterval(() => loadData({ silent: true }), APP_POLL_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [loadData]);

  useEffect(() => {
    const subscription = AppState.addEventListener("change", (state) => {
      if (state === "active" && token) {
        loadData({ silent: true });
      }
    });

    return () => subscription.remove();
  }, [loadData, token]);

  const registerNotifications = useCallback(async () => {
    if (!token) {
      return;
    }

    try {
      setPushStatus("Requesting permission...");
      const expoToken = await getExpoPushToken();
      await API.post("push-token/", {
        token: expoToken,
        platform: Device.osName || "",
        device_name: Device.deviceName || "",
      });
      setPushStatus("Registered");
    } catch (e) {
      setPushStatus(e.message || "Registration failed");
    }
  }, [token]);

  useEffect(() => {
    if (token) {
      registerNotifications();
      registerBackgroundSync();
    }
  }, [token, registerNotifications, registerBackgroundSync]);

  const handleAuth = async () => {
    setLoading(true);
    setError("");

    try {
      const endpoint = authMode === "login" ? "auth/login/" : "auth/signup/";
      const payload =
        authMode === "login"
          ? { username: authForm.username, password: authForm.password }
          : authForm;

      const res = await API.post(endpoint, payload);
      await SecureStore.setItemAsync(TOKEN_KEY, res.data.token);
      setToken(res.data.token);
      setParent(res.data.parent);
    } catch (e) {
      setError(
        e.response?.data?.error ||
          e.response?.data?.username?.[0] ||
          "Authentication failed"
      );
    } finally {
      setLoading(false);
    }
  };

  const logout = async () => {
    await SecureStore.deleteItemAsync(TOKEN_KEY);
    setToken("");
    setParent(null);
    setRows([]);
    setDays([]);
    setDevices([]);
    setChildren([]);
    setNotifications([]);
    setReports([]);
    setSelectedChildId(null);
    setSelectedDeviceId("");
    setPushStatus("Not registered");
    setSyncStatus("Background sync not enabled");
  };

  const saveProfile = async () => {
    setLoading(true);
    try {
      const res = await API.patch("auth/me/", profileForm);
      setParent(res.data);
      Alert.alert("Profile saved", "Parent profile details updated.");
    } catch {
      Alert.alert("Profile error", "Could not save parent profile.");
    } finally {
      setLoading(false);
    }
  };

  const savePassword = async () => {
    setLoading(true);
    try {
      await API.post("auth/change-password/", passwordForm);
      await SecureStore.deleteItemAsync(TOKEN_KEY);
      Alert.alert("Password changed", "Please login again with your new password.");
      setToken("");
      setParent(null);
      setPasswordForm({ current_password: "", new_password: "" });
    } catch (e) {
      Alert.alert("Password error", e.response?.data?.error || "Could not change password.");
    } finally {
      setLoading(false);
    }
  };

  const saveChild = async () => {
    if (!selectedChild) {
      return;
    }

    setLoading(true);
    try {
      await API.patch(`children/${selectedChild.id}/`, {
        name: childForm.name,
        age: childForm.age ? Number(childForm.age) : null,
        weight_kg: childForm.weight_kg ? Number(childForm.weight_kg) : null,
        activity_level: childForm.activity_level,
        heat_sensitivity: childForm.heat_sensitivity,
        school_name: childForm.school_name,
        school_start: childForm.school_start || "08:00",
        school_end: childForm.school_end || "15:00",
        school_mode_enabled: childForm.school_mode_enabled,
        daily_goal_ml: childForm.daily_goal_ml ? Number(childForm.daily_goal_ml) : 4000,
      });
      await loadData();
      Alert.alert("Child saved", "Child profile updated.");
    } catch {
      Alert.alert("Child error", "Could not save child profile.");
    } finally {
      setLoading(false);
    }
  };

  const deleteChild = async () => {
    if (!selectedChild) {
      return;
    }

    Alert.alert(
      "Delete child profile",
      `Delete ${selectedChild.name}? This unpairs linked bottles but keeps bottle data history.`,
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Delete",
          style: "destructive",
          onPress: async () => {
            setLoading(true);
            try {
              await API.delete(`children/${selectedChild.id}/`);
              setSelectedChildId(null);
              setSelectedDeviceId("");
              await loadData();
              Alert.alert("Child deleted", "Child profile was removed and linked bottles were unpaired.");
            } catch {
              Alert.alert("Delete failed", "Could not delete this child profile.");
            } finally {
              setLoading(false);
            }
          },
        },
      ]
    );
  };

  const calibrateBottle = async () => {
    Alert.alert(
      "Calibrate bottle",
      "Keep the bottle empty, upright, and still before starting calibration.",
      [
        { text: "Cancel", style: "cancel" },
        {
          text: "Start",
          onPress: async () => {
            setLoading(true);
            try {
              const res = await API.post("calibrate/");
              await loadData({ silent: true });
              Alert.alert(
                "Calibration complete",
                `Empty distance: ${res.data?.empty_dist ?? "--"} cm`
              );
            } catch (e) {
              Alert.alert("Calibration failed", e.response?.data?.error || "Could not calibrate bottle.");
            } finally {
              setLoading(false);
            }
          },
        },
      ]
    );
  };

  const updateNotificationSetting = async (key, value) => {
    const next = { ...(notificationSettings || {}), [key]: value };
    setNotificationSettings(next);

    try {
      const res = await API.patch("notification-settings/", { [key]: value });
      setNotificationSettings(res.data);
    } catch {
      Alert.alert("Settings error", "Could not save notification setting.");
    }
  };

  const updatePairing = (field, value) => {
    setPairing((current) => ({ ...current, [field]: value }));
  };

  const handleQrScanned = ({ data }) => {
    if (scanned) {
      return;
    }

    setScanned(true);
    const parsed = parsePairingData(data);

    if (!parsed) {
      Alert.alert("Invalid QR", "This QR code is not a smart bottle pairing code.");
      setScanned(false);
      return;
    }

    setPairing((current) => ({
      ...current,
      device_id: parsed.device_id,
      pairing_token: parsed.pairing_token,
    }));
    setScannerOpen(false);
  };

  const openScanner = async () => {
    if (!permission?.granted) {
      const result = await requestPermission();
      if (!result.granted) {
        Alert.alert("Camera permission", "Camera permission is required to scan the bottle QR code.");
        return;
      }
    }

    setScanned(false);
    setScannerOpen(true);
  };

  const pairBottle = async () => {
    if (!pairing.child_name.trim()) {
      Alert.alert("Child name required", "Enter the child name before pairing the bottle.");
      return;
    }

    if (!pairing.device_id.trim() || !pairing.pairing_token.trim()) {
      Alert.alert("QR required", "Scan the bottle QR code or enter device ID and pairing token manually.");
      return;
    }

    setLoading(true);
    setError("");

    try {
      await API.post("devices/pair/", {
        device_id: pairing.device_id.trim(),
        pairing_token: pairing.pairing_token.trim(),
        child_name: pairing.child_name.trim(),
        age: pairing.age ? Number(pairing.age) : null,
        school_name: pairing.school_name.trim(),
      });

      setPairing({
        child_name: "",
        age: "",
        school_name: "",
        device_id: "",
        pairing_token: "",
      });
      await loadData();
      Alert.alert("Bottle paired", "The smart bottle is now linked to this parent account.");
    } catch (e) {
      setError(e.response?.data?.error || "Bottle pairing failed");
    } finally {
      setLoading(false);
    }
  };

  const events = useMemo(
    () => rows.filter((row) => ["FILL", "DRINK", "DROP"].includes(row.event)).slice(0, 8),
    [rows]
  );

  if (restoringSession) {
    return (
      <SafeAreaView style={styles.safe}>
        <View style={styles.loadingScreen}>
          <ActivityIndicator />
          <Text style={styles.muted}>Restoring parent session...</Text>
        </View>
      </SafeAreaView>
    );
  }

  if (!token) {
    return (
      <SafeAreaView style={styles.safe}>
        <StatusBar style="dark" />
        <View style={styles.authPage}>
          <View>
            <Text style={styles.eyebrow}>Smart Bottle</Text>
            <Text style={styles.authTitle}>Parent Control</Text>
            <Text style={styles.authSubtitle}>
              Monitor hydration, alerts, drops, and daily progress from your phone.
            </Text>
          </View>

          <View style={styles.authCard}>
            <View style={styles.segment}>
              <Pressable
                style={[styles.segmentBtn, authMode === "login" && styles.segmentActive]}
                onPress={() => setAuthMode("login")}
              >
                <Text style={styles.segmentText}>Login</Text>
              </Pressable>
              <Pressable
                style={[styles.segmentBtn, authMode === "signup" && styles.segmentActive]}
                onPress={() => setAuthMode("signup")}
              >
                <Text style={styles.segmentText}>Signup</Text>
              </Pressable>
            </View>

            <Input
              label="Username"
              value={authForm.username}
              onChangeText={(username) => setAuthForm((form) => ({ ...form, username }))}
            />
            {authMode === "signup" ? (
              <>
                <Input
                  label="Email"
                  value={authForm.email}
                  onChangeText={(email) => setAuthForm((form) => ({ ...form, email }))}
                />
                <Input
                  label="Phone"
                  value={authForm.phone}
                  onChangeText={(phone) => setAuthForm((form) => ({ ...form, phone }))}
                />
              </>
            ) : null}
            <Input
              label="Password"
              secureTextEntry
              value={authForm.password}
              onChangeText={(password) => setAuthForm((form) => ({ ...form, password }))}
            />

            {error ? <Text style={styles.error}>{error}</Text> : null}

            <Pressable style={styles.primaryBtn} onPress={handleAuth} disabled={loading}>
              {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>{authMode === "login" ? "Login" : "Create Account"}</Text>}
            </Pressable>
          </View>

          <Text style={styles.apiText}>{API_BASE_URL}</Text>
        </View>
      </SafeAreaView>
    );
  }

  const goal = Number(latest?.goal || 4000);
  const intake = Number(latest?.water_intake || 0);
  const balance = Number(latest?.balance_ml ?? latest?.water_ml ?? 0);
  const progress = Math.min(100, goal > 0 ? (intake / goal) * 100 : 0);
  const bottleLevel = Number(latest?.bottle_level || 0);

  const renderContent = () => {
    if (activeMenu === "pair") {
      return (
        <PairingCard
          pairing={pairing}
          updatePairing={updatePairing}
          openScanner={openScanner}
          pairBottle={pairBottle}
          loading={loading}
        />
      );
    }

    if (activeMenu === "profile") {
      return (
        <ProfileScreen
          profileForm={profileForm}
          setProfileForm={setProfileForm}
          passwordForm={passwordForm}
          setPasswordForm={setPasswordForm}
          childForm={childForm}
          setChildForm={setChildForm}
          selectedChild={selectedChild}
          saveProfile={saveProfile}
          savePassword={savePassword}
          saveChild={saveChild}
          deleteChild={deleteChild}
          loading={loading}
        />
      );
    }

    if (activeMenu === "reports") {
      return (
        <ReportsScreen
          report={selectedReport}
          days={selectedReport?.days || days}
          events={selectedReport?.events || events}
          alerts={selectedReport?.alerts || []}
        />
      );
    }

    if (activeMenu === "settings") {
      return (
        <SettingsScreen
          pushStatus={pushStatus}
          syncStatus={syncStatus}
          registerNotifications={registerNotifications}
          registerBackgroundSync={registerBackgroundSync}
          loadData={() => loadData({ silent: false })}
          notificationSettings={notificationSettings}
          updateNotificationSetting={updateNotificationSetting}
          notifications={notifications}
          calibrateBottle={calibrateBottle}
          selectedDevice={selectedDevice}
          loading={loading}
        />
      );
    }

    return (
      <>
        {children.length ? (
          <SelectorSection
            title="Children"
            items={children}
            selectedKey={selectedChild?.id}
            getKey={(child) => child.id}
            getLabel={(child) => child.name}
            getSubLabel={(child) => child.school_name || `${child.age ?? "--"} years`}
            onSelect={(child) => {
              setSelectedChildId(child.id);
              const nextDevices = devices.filter((device) => device.child === child.id);
              setSelectedDeviceId(nextDevices[0]?.device_id || "");
            }}
          />
        ) : null}

        {visibleDevices.length ? (
          <SelectorSection
            title="Bottles"
            items={visibleDevices}
            selectedKey={selectedDevice?.device_id}
            getKey={(device) => device.device_id}
            getLabel={(device) => device.name || device.device_id}
            getSubLabel={(device) => device.child_name || device.device_id}
            onSelect={(device) => setSelectedDeviceId(device.device_id)}
          />
        ) : null}

        {!devices.length ? (
          <PairingCard
            pairing={pairing}
            updatePairing={updatePairing}
            openScanner={openScanner}
            pairBottle={pairBottle}
            loading={loading}
          />
        ) : null}

        <View style={styles.hero}>
          <View style={styles.heroTop}>
            <View>
              <Text style={styles.childName}>{selectedChild?.name || "School Hydration"}</Text>
              <Text style={styles.deviceText}>
                {selectedDevice?.device_id || "No bottle paired"} | {selectedReport?.is_online ? "Online" : "Offline"}
              </Text>
            </View>
            <View style={[styles.badge, !selectedReport?.is_online && styles.badgeOffline]}>
              <Text style={styles.badgeText}>
                {selectedReport?.is_online ? "ONLINE" : "OFFLINE"}
              </Text>
            </View>
          </View>

          <View style={styles.metricRow}>
            <View>
              <Text style={styles.metricValue}>{formatMl(intake)}</Text>
              <Text style={styles.metricLabel}>Drunk today</Text>
            </View>
            <View style={styles.bottle}>
              <View style={[styles.water, { height: `${Math.max(4, bottleLevel)}%` }]} />
            </View>
          </View>

          <View style={styles.progressTrack}>
            <View style={[styles.progressFill, { width: `${progress}%` }]} />
          </View>
          <Text style={styles.goalText}>Goal {formatMl(goal)} | Balance {formatMl(balance)}</Text>
        </View>

        <View style={styles.grid}>
          <InfoCard icon="water-outline" label="Filled" value={formatMl(latest?.total_filled)} />
          <InfoCard icon="arrow-down-outline" label="Dropped" value={formatMl(latest?.total_dropped)} />
          <InfoCard icon="thermometer-outline" label="Temp" value={`${latest?.temperature ?? "--"} C`} />
          <InfoCard icon="time-outline" label="Next Drink" value={formatTime(latest?.next_reminder_time)} />
          <InfoCard icon="pulse-outline" label="Sensor" value={`${Number(latest?.sensor_health || 0).toFixed(0)}%`} />
          <InfoCard icon="walk-outline" label="Movement" value={latest?.movement_state || "STABLE"} />
        </View>

        {latest?.alert ? (
          <View style={styles.alert}>
            <Ionicons name="warning-outline" size={20} color="#92400e" />
            <Text style={styles.alertText}>{latest.alert}</Text>
          </View>
        ) : null}

        {selectedReport && !selectedReport.is_online ? (
          <View style={styles.offlineAlert}>
            <Ionicons name="cloud-offline-outline" size={20} color="#991b1b" />
            <Text style={styles.offlineText}>
              Smart bottle is offline. Last seen {formatDateTime(selectedReport.device?.last_seen)}.
            </Text>
          </View>
        ) : null}

        <Section title="Recent Events">
          {events.length ? (
            events.map((event) => (
              <View key={`${event.id}-${event.timestamp}`} style={styles.eventRow}>
                <View style={styles.eventIcon}>
                  <Ionicons
                    name={event.event === "DRINK" ? "cafe-outline" : event.event === "DROP" ? "alert-outline" : "add-outline"}
                    size={18}
                    color="#0f172a"
                  />
                </View>
                <View style={styles.eventTextWrap}>
                  <Text style={styles.eventTitle}>{event.event}</Text>
                  <Text style={styles.muted}>{event.direction || "NORMAL"}</Text>
                </View>
                <Text style={styles.eventAmount}>{formatMl(event.event_amount)}</Text>
              </View>
            ))
          ) : (
            <Text style={styles.muted}>No fill, drink, or drop events yet.</Text>
          )}
        </Section>

        <Section title="15-Day Goal">
          <View style={styles.dayGrid}>
            {days.map((day) => (
              <View key={day.date} style={styles.dayItem}>
                <View
                  style={[
                    styles.dayBar,
                    { height: `${Math.max(8, Math.min(100, (day.water_intake / day.goal) * 100))}%` },
                    day.completed ? styles.dayComplete : styles.dayMissed,
                  ]}
                />
                <Text style={styles.dayLabel}>{day.label.split(" ")[0]}</Text>
              </View>
            ))}
          </View>
        </Section>
      </>
    );
  };

  if (scannerOpen) {
    return (
      <SafeAreaView style={styles.scannerPage}>
        <StatusBar style="light" />
        <CameraView
          style={styles.camera}
          facing="back"
          barcodeScannerSettings={{ barcodeTypes: ["qr"] }}
          onBarcodeScanned={scanned ? undefined : handleQrScanned}
        >
          <View style={styles.scannerOverlay}>
            <View style={styles.scannerTop}>
              <Pressable style={styles.scannerClose} onPress={() => setScannerOpen(false)}>
                <Ionicons name="close" size={24} color="#fff" />
              </Pressable>
            </View>
            <View style={styles.scanBox} />
            <Text style={styles.scannerText}>Scan the smart bottle QR code</Text>
          </View>
        </CameraView>
      </SafeAreaView>
    );
  }

  return (
    <SafeAreaView style={styles.safe}>
      <StatusBar style="dark" />
      <ScrollView
        style={styles.page}
        contentContainerStyle={[
          styles.content,
          { paddingBottom: Math.max(108, insets.bottom + 92) },
        ]}
      >
        <View style={styles.header}>
          <View>
            <Text style={styles.eyebrow}>Parent Control</Text>
            <Text style={styles.title}>Smart Bottle</Text>
            <Text style={styles.muted}>{parent?.username || "Parent"}</Text>
          </View>
          <View style={styles.headerActions}>
            <Pressable style={styles.iconButton} onPress={() => loadData({ silent: false })}>
              <Ionicons name="refresh" size={20} color="#0f172a" />
            </Pressable>
            <Pressable style={styles.iconButton} onPress={logout}>
              <Ionicons name="log-out-outline" size={20} color="#0f172a" />
            </Pressable>
          </View>
        </View>

        {loading ? (
          <View style={styles.loading}>
            <ActivityIndicator />
            <Text style={styles.muted}>Syncing bottle data...</Text>
          </View>
        ) : null}

        {error ? <Text style={styles.error}>{error}</Text> : null}

        {renderContent()}
      </ScrollView>
      <MenuBar activeMenu={activeMenu} setActiveMenu={setActiveMenu} bottomInset={insets.bottom} />
    </SafeAreaView>
  );
}

export default function App() {
  return (
    <SafeAreaProvider>
      <AppContent />
    </SafeAreaProvider>
  );
}

function PairingCard({ pairing, updatePairing, openScanner, pairBottle, loading, compact }) {
  return (
    <View style={styles.section}>
      <View style={styles.sectionHeader}>
        <View>
          <Text style={styles.sectionTitle}>{compact ? "Pair Another Bottle" : "Pair A Bottle"}</Text>
          <Text style={styles.muted}>Create child profile and scan the QR code.</Text>
        </View>
        <Pressable style={styles.scanBtn} onPress={openScanner}>
          <Ionicons name="qr-code-outline" size={20} color="#fff" />
        </Pressable>
      </View>

      <Input
        label="Child Name"
        value={pairing.child_name}
        onChangeText={(value) => updatePairing("child_name", value)}
      />
      <View style={styles.twoColumn}>
        <View style={styles.flexOne}>
          <Input
            label="Age"
            keyboardType="number-pad"
            value={pairing.age}
            onChangeText={(value) => updatePairing("age", value)}
          />
        </View>
        <View style={styles.flexOne}>
          <Input
            label="School"
            value={pairing.school_name}
            onChangeText={(value) => updatePairing("school_name", value)}
          />
        </View>
      </View>

      <Input
        label="Device ID"
        value={pairing.device_id}
        onChangeText={(value) => updatePairing("device_id", value)}
      />
      <Input
        label="Pairing Token"
        value={pairing.pairing_token}
        onChangeText={(value) => updatePairing("pairing_token", value)}
      />

      <Pressable style={styles.primaryBtn} onPress={pairBottle} disabled={loading}>
        {loading ? <ActivityIndicator color="#fff" /> : <Text style={styles.primaryText}>Pair Bottle</Text>}
      </Pressable>
    </View>
  );
}

function ProfileScreen({
  profileForm,
  setProfileForm,
  passwordForm,
  setPasswordForm,
  childForm,
  setChildForm,
  selectedChild,
  saveProfile,
  savePassword,
  saveChild,
  deleteChild,
  loading,
}) {
  return (
    <>
      <Section title="Parent Profile">
        <Input
          label="Email"
          value={profileForm.email}
          onChangeText={(email) => setProfileForm((form) => ({ ...form, email }))}
        />
        <Input
          label="Phone"
          value={profileForm.phone}
          onChangeText={(phone) => setProfileForm((form) => ({ ...form, phone }))}
        />
        <Pressable style={styles.primaryBtn} onPress={saveProfile} disabled={loading}>
          <Text style={styles.primaryText}>Save Parent Profile</Text>
        </Pressable>
      </Section>

      <Section title="Change Password">
        <Input
          label="Current Password"
          secureTextEntry
          value={passwordForm.current_password}
          onChangeText={(current_password) =>
            setPasswordForm((form) => ({ ...form, current_password }))
          }
        />
        <Input
          label="New Password"
          secureTextEntry
          value={passwordForm.new_password}
          onChangeText={(new_password) =>
            setPasswordForm((form) => ({ ...form, new_password }))
          }
        />
        <Pressable style={styles.secondaryBtn} onPress={savePassword} disabled={loading}>
          <Text style={styles.secondaryText}>Change Password</Text>
        </Pressable>
      </Section>

      <Section title="Child Profile">
        {selectedChild ? (
          <>
            <Input
              label="Child Name"
              value={childForm.name}
              onChangeText={(name) => setChildForm((form) => ({ ...form, name }))}
            />
            <View style={styles.twoColumn}>
              <View style={styles.flexOne}>
                <Input
                  label="Age"
                  keyboardType="number-pad"
                  value={childForm.age}
                  onChangeText={(age) => setChildForm((form) => ({ ...form, age }))}
                />
              </View>
              <View style={styles.flexOne}>
                <Input
                  label="Weight Kg"
                  keyboardType="number-pad"
                  value={childForm.weight_kg}
                  onChangeText={(weight_kg) =>
                    setChildForm((form) => ({ ...form, weight_kg }))
                  }
                />
              </View>
            </View>
            <View style={styles.segment}>
              {["low", "normal", "high"].map((level) => (
                <Pressable
                  key={level}
                  style={[
                    styles.segmentBtn,
                    childForm.activity_level === level && styles.segmentActive,
                  ]}
                  onPress={() => setChildForm((form) => ({ ...form, activity_level: level }))}
                >
                  <Text style={styles.segmentText}>{level.toUpperCase()}</Text>
                </Pressable>
              ))}
            </View>
            <ToggleRow
              label="Heat sensitive child"
              value={childForm.heat_sensitivity}
              onPress={() =>
                setChildForm((form) => ({
                  ...form,
                  heat_sensitivity: !form.heat_sensitivity,
                }))
              }
            />
            <ToggleRow
              label="School mode reminders"
              value={childForm.school_mode_enabled}
              onPress={() =>
                setChildForm((form) => ({
                  ...form,
                  school_mode_enabled: !form.school_mode_enabled,
                }))
              }
            />
            <Text style={styles.muted}>
              During school time the bottle can be offline for longer without showing urgent offline status. Stored events send when Wi-Fi returns.
            </Text>
            <Input
              label="School"
              value={childForm.school_name}
              onChangeText={(school_name) =>
                setChildForm((form) => ({ ...form, school_name }))
              }
            />
            <View style={styles.twoColumn}>
              <View style={styles.flexOne}>
                <Input
                  label="School Start"
                  value={childForm.school_start}
                  onChangeText={(school_start) =>
                    setChildForm((form) => ({ ...form, school_start }))
                  }
                />
              </View>
              <View style={styles.flexOne}>
                <Input
                  label="School End"
                  value={childForm.school_end}
                  onChangeText={(school_end) =>
                    setChildForm((form) => ({ ...form, school_end }))
                  }
                />
              </View>
            </View>
            <Input
              label={`Daily Goal (suggested ${formatMl(selectedChild.recommended_goal_ml)})`}
              keyboardType="number-pad"
              value={childForm.daily_goal_ml}
              onChangeText={(daily_goal_ml) =>
                setChildForm((form) => ({ ...form, daily_goal_ml }))
              }
            />
            <Pressable style={styles.primaryBtn} onPress={saveChild} disabled={loading}>
              <Text style={styles.primaryText}>Save Child Profile</Text>
            </Pressable>
            <Pressable style={styles.dangerBtn} onPress={deleteChild} disabled={loading}>
              <Text style={styles.dangerText}>Delete Child Profile</Text>
            </Pressable>
          </>
        ) : (
          <Text style={styles.muted}>Pair a bottle to create a child profile first.</Text>
        )}
      </Section>
    </>
  );
}

function ReportsScreen({ report, days, events, alerts }) {
  const summary = report?.summary || {};
  const latest = report?.latest || {};
  const completedPercent = days?.length
    ? Math.round((Number(summary.completed_days || 0) / days.length) * 100)
    : 0;

  return (
    <>
      <Section title="Reports & Alerts">
        <View style={styles.reportHero}>
          <View>
            <Text style={styles.metricValue}>{completedPercent}%</Text>
            <Text style={styles.metricLabel}>15-day completion</Text>
          </View>
          <View style={styles.reportStatus}>
            <Text style={styles.eventTitle}>{report?.is_online ? "Bottle Online" : "Bottle Offline"}</Text>
            <Text style={styles.muted}>School mode {report?.school_mode_active ? "active" : "inactive"}</Text>
          </View>
        </View>
        <View style={styles.grid}>
          <InfoCard icon="checkmark-circle-outline" label="Goal Days" value={`${summary.completed_days || 0}`} />
          <InfoCard icon="close-circle-outline" label="Missed Days" value={`${summary.missed_days || 0}`} />
          <InfoCard icon="cafe-outline" label="Drink Events" value={`${summary.total_drink_events || 0}`} />
          <InfoCard icon="alert-outline" label="Drop Events" value={`${summary.total_drop_events || 0}`} />
          <InfoCard icon="pulse-outline" label="Sensor" value={`${Number(latest.sensor_health || 0).toFixed(0)}%`} />
          <InfoCard icon="walk-outline" label="Movement" value={latest.movement_state || "--"} />
        </View>
        <Text style={styles.goalText}>
          Today {formatMl(summary.today_intake)} / {formatMl(summary.today_goal || latest.goal)}
        </Text>
      </Section>

      <Section title="15-Day Progress">
        <View style={styles.dayGrid}>
          {(days || []).map((day) => (
            <View key={day.date} style={styles.dayItem}>
              <View
                style={[
                  styles.dayBar,
                  { height: `${Math.max(8, Math.min(100, (day.water_intake / day.goal) * 100))}%` },
                  day.completed ? styles.dayComplete : styles.dayMissed,
                ]}
              />
              <Text style={styles.dayLabel}>{day.label.split(" ")[0]}</Text>
            </View>
          ))}
        </View>
      </Section>

      <Section title="Alert History">
        {alerts?.length ? (
          alerts.slice(0, 8).map((item) => (
            <View key={`${item.id}-alert`} style={styles.eventRow}>
              <View style={styles.eventIcon}>
                <Ionicons name="warning-outline" size={18} color="#92400e" />
              </View>
              <View style={styles.eventTextWrap}>
                <Text style={styles.eventTitle}>{item.alert}</Text>
                <Text style={styles.muted}>{formatDateTime(item.timestamp)}</Text>
              </View>
            </View>
          ))
        ) : (
          <Text style={styles.muted}>No alert history yet.</Text>
        )}
      </Section>

      <Section title="Drink / Fill / Drop History">
        {events?.length ? (
          events.slice(0, 10).map((event) => (
            <View key={`${event.id}-${event.timestamp}`} style={styles.eventRow}>
              <View style={styles.eventIcon}>
                <Ionicons
                  name={event.event === "DRINK" ? "cafe-outline" : event.event === "DROP" ? "alert-outline" : "add-outline"}
                  size={18}
                  color="#0f172a"
                />
              </View>
              <View style={styles.eventTextWrap}>
                <Text style={styles.eventTitle}>{event.event}</Text>
                <Text style={styles.muted}>{formatDateTime(event.timestamp)}</Text>
              </View>
              <Text style={styles.eventAmount}>{formatMl(event.event_amount)}</Text>
            </View>
          ))
        ) : (
          <Text style={styles.muted}>No event history yet.</Text>
        )}
      </Section>
    </>
  );
}

function SettingsScreen({
  pushStatus,
  syncStatus,
  registerNotifications,
  registerBackgroundSync,
  loadData,
  notificationSettings,
  updateNotificationSetting,
  notifications,
  calibrateBottle,
  selectedDevice,
  loading,
}) {
  const settings = notificationSettings || {};
  const toggles = [
    ["drink_reminder", "Drink reminders"],
    ["behind_goal", "Behind goal"],
    ["low_water", "Low water"],
    ["bottle_empty", "Bottle empty"],
    ["drop_detected", "Drop detected"],
    ["extreme_heat", "Extreme heat"],
    ["quiet_hours_enabled", "Quiet hours"],
  ];

  return (
    <>
      <Section title="Notification Settings">
        <View style={styles.sectionHeader}>
          <View>
            <Text style={styles.eventTitle}>Push Status</Text>
            <Text style={styles.muted}>{pushStatus}</Text>
          </View>
          <Pressable style={styles.scanBtn} onPress={registerNotifications}>
            <Ionicons name="notifications-outline" size={20} color="#fff" />
          </Pressable>
        </View>
        {toggles.map(([key, label]) => (
          <ToggleRow
            key={key}
            label={label}
            value={Boolean(settings[key])}
            onPress={() => updateNotificationSetting(key, !settings[key])}
          />
        ))}
      </Section>

      <Section title="Bottle Calibration">
        <View style={styles.sectionHeader}>
          <View style={styles.eventTextWrap}>
            <Text style={styles.eventTitle}>{selectedDevice?.name || selectedDevice?.device_id || "Selected bottle"}</Text>
            <Text style={styles.muted}>Keep the bottle empty, upright, and still.</Text>
          </View>
          <Pressable
            style={[styles.scanBtn, (!selectedDevice || loading) && styles.disabledBtn]}
            onPress={calibrateBottle}
            disabled={!selectedDevice || loading}
          >
            <Ionicons name="speedometer-outline" size={20} color="#fff" />
          </Pressable>
        </View>
      </Section>

      <Section title="Background Sync">
        <View style={styles.sectionHeader}>
          <View style={styles.eventTextWrap}>
            <Text style={styles.eventTitle}>Data Refresh</Text>
            <Text style={styles.muted}>{syncStatus}</Text>
          </View>
          <View style={styles.syncActions}>
            <Pressable style={styles.smallActionBtn} onPress={loadData}>
              <Ionicons name="refresh" size={18} color="#0f172a" />
            </Pressable>
            <Pressable style={styles.scanBtn} onPress={registerBackgroundSync}>
              <Ionicons name="cloud-download-outline" size={20} color="#fff" />
            </Pressable>
          </View>
        </View>
        <Text style={styles.muted}>
          The app refreshes when opened and asks the phone to sync in the background every 15 minutes when the OS allows it.
        </Text>
      </Section>

      <NotificationsSection notifications={notifications} />
    </>
  );
}

function ToggleRow({ label, value, onPress }) {
  return (
    <Pressable style={styles.toggleRow} onPress={onPress}>
      <Text style={styles.eventTitle}>{label}</Text>
      <View style={[styles.toggleTrack, value && styles.toggleTrackOn]}>
        <View style={[styles.toggleThumb, value && styles.toggleThumbOn]} />
      </View>
    </Pressable>
  );
}

function MenuBar({ activeMenu, setActiveMenu, bottomInset }) {
  const items = [
    ["home", "Home", "home-outline"],
    ["reports", "Reports", "bar-chart-outline"],
    ["pair", "Pair", "qr-code-outline"],
    ["profile", "Profile", "person-outline"],
    ["settings", "Settings", "settings-outline"],
  ];

  return (
    <View style={[styles.menuBar, { paddingBottom: Math.max(8, bottomInset + 8) }]}>
      {items.map(([key, label, icon]) => {
        const active = activeMenu === key;
        return (
          <Pressable
            key={key}
            style={styles.menuItem}
            onPress={() => setActiveMenu(key)}
          >
            <Ionicons name={icon} size={21} color={active ? "#2563eb" : "#64748b"} />
            <Text style={[styles.menuLabel, active && styles.menuLabelActive]}>{label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

function SelectorSection({ title, items, selectedKey, getKey, getLabel, getSubLabel, onSelect }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.selectorRow}>
        {items.map((item) => {
          const key = getKey(item);
          const active = key === selectedKey;

          return (
            <Pressable
              key={key}
              style={[styles.selectorChip, active && styles.selectorChipActive]}
              onPress={() => onSelect(item)}
            >
              <Text style={[styles.selectorTitle, active && styles.selectorTitleActive]}>
                {getLabel(item)}
              </Text>
              <Text style={[styles.selectorSub, active && styles.selectorSubActive]}>
                {getSubLabel(item)}
              </Text>
            </Pressable>
          );
        })}
      </ScrollView>
    </View>
  );
}

function NotificationsSection({ notifications }) {
  return (
    <Section title="Notifications">
      {notifications.length ? (
        notifications.slice(0, 8).map((item) => (
          <View key={item.id} style={styles.notificationRow}>
            <View style={styles.notificationIcon}>
              <Ionicons
                name={item.delivered ? "checkmark-circle-outline" : "time-outline"}
                size={18}
                color={item.delivered ? "#15803d" : "#92400e"}
              />
            </View>
            <View style={styles.eventTextWrap}>
              <Text style={styles.eventTitle}>{item.title}</Text>
              <Text style={styles.muted}>{item.body}</Text>
            </View>
          </View>
        ))
      ) : (
        <Text style={styles.muted}>No notification history yet.</Text>
      )}
    </Section>
  );
}

function Input({ label, ...props }) {
  return (
    <View style={styles.inputWrap}>
      <Text style={styles.inputLabel}>{label}</Text>
      <TextInput style={styles.input} placeholderTextColor="#94a3b8" {...props} />
    </View>
  );
}

function InfoCard({ icon, label, value }) {
  return (
    <View style={styles.infoCard}>
      <Ionicons name={icon} size={20} color="#2563eb" />
      <Text style={styles.infoLabel}>{label}</Text>
      <Text style={styles.infoValue}>{value}</Text>
    </View>
  );
}

function Section({ title, children }) {
  return (
    <View style={styles.section}>
      <Text style={styles.sectionTitle}>{title}</Text>
      {children}
    </View>
  );
}

const styles = StyleSheet.create({
  safe: { flex: 1, backgroundColor: "#f6f8fb" },
  page: { flex: 1 },
  content: { padding: 18, gap: 14 },
  loadingScreen: { flex: 1, justifyContent: "center", alignItems: "center", gap: 10 },
  authPage: { flex: 1, padding: 22, justifyContent: "center", gap: 18, backgroundColor: "#f6f8fb" },
  authTitle: { color: "#0f172a", fontSize: 34, fontWeight: "900" },
  authSubtitle: { color: "#64748b", marginTop: 8, fontSize: 15, lineHeight: 22 },
  authCard: { backgroundColor: "#fff", borderRadius: 8, padding: 16, gap: 12 },
  segment: { flexDirection: "row", backgroundColor: "#f1f5f9", borderRadius: 8, padding: 4 },
  segmentBtn: { flex: 1, padding: 10, alignItems: "center", borderRadius: 6 },
  segmentActive: { backgroundColor: "#fff" },
  segmentText: { color: "#0f172a", fontWeight: "800" },
  inputWrap: { gap: 6 },
  inputLabel: { color: "#475569", fontSize: 13, fontWeight: "700" },
  input: { borderWidth: 1, borderColor: "#e2e8f0", borderRadius: 8, padding: 12, color: "#0f172a" },
  primaryBtn: { backgroundColor: "#2563eb", borderRadius: 8, padding: 14, alignItems: "center" },
  primaryText: { color: "#fff", fontWeight: "900" },
  secondaryBtn: { backgroundColor: "#f8fafc", borderWidth: 1, borderColor: "#cbd5e1", borderRadius: 8, padding: 14, alignItems: "center" },
  secondaryText: { color: "#0f172a", fontWeight: "900" },
  dangerBtn: { backgroundColor: "#fff1f2", borderWidth: 1, borderColor: "#fecdd3", borderRadius: 8, padding: 14, alignItems: "center" },
  dangerText: { color: "#be123c", fontWeight: "900" },
  disabledBtn: { opacity: 0.45 },
  apiText: { color: "#64748b", fontSize: 12, textAlign: "center" },
  header: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  headerActions: { flexDirection: "row", gap: 8 },
  eyebrow: { color: "#2563eb", fontSize: 13, fontWeight: "700" },
  title: { color: "#0f172a", fontSize: 30, fontWeight: "800" },
  iconButton: { width: 42, height: 42, borderRadius: 21, backgroundColor: "#fff", alignItems: "center", justifyContent: "center" },
  loading: { alignItems: "center", padding: 20 },
  error: { color: "#dc2626", fontWeight: "700" },
  hero: { backgroundColor: "#fff", borderRadius: 8, padding: 18, gap: 14 },
  heroTop: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  childName: { fontSize: 18, fontWeight: "800", color: "#0f172a" },
  deviceText: { color: "#64748b", marginTop: 2 },
  badge: { backgroundColor: "#e0f2fe", paddingHorizontal: 10, paddingVertical: 6, borderRadius: 999 },
  badgeOffline: { backgroundColor: "#fee2e2" },
  badgeText: { color: "#0369a1", fontWeight: "800", fontSize: 12 },
  metricRow: { flexDirection: "row", justifyContent: "space-between", alignItems: "center" },
  metricValue: { fontSize: 38, fontWeight: "900", color: "#0f172a" },
  metricLabel: { color: "#64748b", marginTop: 4 },
  bottle: { width: 72, height: 140, borderWidth: 4, borderColor: "#1f2937", borderRadius: 22, overflow: "hidden", justifyContent: "flex-end", backgroundColor: "#f8fafc" },
  water: { backgroundColor: "#22c5f3", width: "100%" },
  progressTrack: { height: 10, backgroundColor: "#e5e7eb", borderRadius: 999, overflow: "hidden" },
  progressFill: { height: "100%", backgroundColor: "#22c55e" },
  goalText: { color: "#475569", fontWeight: "600" },
  grid: { flexDirection: "row", flexWrap: "wrap", gap: 10 },
  infoCard: { width: "48%", backgroundColor: "#fff", borderRadius: 8, padding: 14, gap: 6 },
  infoLabel: { color: "#64748b", fontSize: 12, fontWeight: "700" },
  infoValue: { color: "#0f172a", fontSize: 18, fontWeight: "800" },
  alert: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#fef3c7", borderRadius: 8, padding: 12 },
  alertText: { color: "#92400e", fontWeight: "700", flex: 1 },
  offlineAlert: { flexDirection: "row", alignItems: "center", gap: 8, backgroundColor: "#fee2e2", borderRadius: 8, padding: 12 },
  offlineText: { color: "#991b1b", fontWeight: "800", flex: 1 },
  section: { backgroundColor: "#fff", borderRadius: 8, padding: 14, gap: 10 },
  sectionHeader: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 },
  sectionTitle: { color: "#0f172a", fontSize: 17, fontWeight: "800" },
  selectorRow: { gap: 10, paddingTop: 2 },
  selectorChip: {
    minWidth: 140,
    borderWidth: 1,
    borderColor: "#e2e8f0",
    backgroundColor: "#f8fafc",
    borderRadius: 8,
    padding: 12,
  },
  selectorChipActive: {
    borderColor: "#2563eb",
    backgroundColor: "#eff6ff",
  },
  selectorTitle: { color: "#0f172a", fontWeight: "900" },
  selectorTitleActive: { color: "#1d4ed8" },
  selectorSub: { color: "#64748b", fontSize: 12, marginTop: 3 },
  selectorSubActive: { color: "#2563eb" },
  scanBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: "#2563eb", alignItems: "center", justifyContent: "center" },
  syncActions: { flexDirection: "row", alignItems: "center", gap: 8 },
  smallActionBtn: { width: 44, height: 44, borderRadius: 22, backgroundColor: "#f8fafc", borderWidth: 1, borderColor: "#e2e8f0", alignItems: "center", justifyContent: "center" },
  twoColumn: { flexDirection: "row", gap: 10 },
  flexOne: { flex: 1 },
  eventRow: { flexDirection: "row", alignItems: "center", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: "#f1f5f9" },
  eventIcon: { width: 34, height: 34, borderRadius: 17, backgroundColor: "#f1f5f9", alignItems: "center", justifyContent: "center", marginRight: 10 },
  eventTextWrap: { flex: 1 },
  eventTitle: { color: "#0f172a", fontWeight: "800" },
  eventAmount: { color: "#0f172a", fontWeight: "800" },
  reportHero: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", gap: 12 },
  reportStatus: { flex: 1, backgroundColor: "#f8fafc", borderRadius: 8, padding: 12, alignItems: "flex-end" },
  notificationRow: { flexDirection: "row", alignItems: "flex-start", paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: "#f1f5f9" },
  notificationIcon: { width: 34, height: 34, borderRadius: 17, backgroundColor: "#f8fafc", alignItems: "center", justifyContent: "center", marginRight: 10 },
  toggleRow: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingVertical: 10, borderBottomWidth: 1, borderBottomColor: "#f1f5f9" },
  toggleTrack: { width: 46, height: 26, borderRadius: 13, backgroundColor: "#cbd5e1", padding: 3 },
  toggleTrackOn: { backgroundColor: "#2563eb" },
  toggleThumb: { width: 20, height: 20, borderRadius: 10, backgroundColor: "#fff" },
  toggleThumbOn: { transform: [{ translateX: 20 }] },
  menuBar: {
    flexDirection: "row",
    backgroundColor: "#fff",
    borderTopWidth: 1,
    borderTopColor: "#e2e8f0",
    paddingVertical: 8,
    paddingHorizontal: 6,
  },
  menuItem: { flex: 1, alignItems: "center", gap: 3 },
  menuLabel: { fontSize: 11, color: "#64748b", fontWeight: "800" },
  menuLabelActive: { color: "#2563eb" },
  muted: { color: "#64748b" },
  dayGrid: { flexDirection: "row", alignItems: "flex-end", gap: 6, height: 120 },
  dayItem: { flex: 1, height: "100%", justifyContent: "flex-end", alignItems: "center", gap: 4 },
  dayBar: { width: "70%", borderRadius: 5 },
  dayComplete: { backgroundColor: "#22c55e" },
  dayMissed: { backgroundColor: "#ef4444" },
  dayLabel: { color: "#64748b", fontSize: 10 },
  scannerPage: { flex: 1, backgroundColor: "#000" },
  camera: { flex: 1 },
  scannerOverlay: { flex: 1, justifyContent: "center", alignItems: "center", padding: 24 },
  scannerTop: { position: "absolute", top: 22, left: 18, right: 18, flexDirection: "row", justifyContent: "flex-end" },
  scannerClose: { width: 44, height: 44, borderRadius: 22, backgroundColor: "rgba(15, 23, 42, 0.72)", alignItems: "center", justifyContent: "center" },
  scanBox: { width: 240, height: 240, borderWidth: 4, borderColor: "#38bdf8", borderRadius: 18, backgroundColor: "rgba(255,255,255,0.05)" },
  scannerText: { color: "#fff", fontSize: 16, fontWeight: "800", marginTop: 22, textAlign: "center" },
});
