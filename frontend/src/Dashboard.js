import React, { useCallback, useEffect, useMemo, useState } from "react";
import API from "./api";
import { QRCodeSVG } from "qrcode.react";
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import Bottle from "./components/Bottle";

const DEFAULT_DEVICE_ID = "bottle_01";

function Spinner() {
  return <span style={styles.spinner} />;
}

function formatMl(value, digits = 0) {
  const numberValue = Number(value || 0);
  return `${numberValue.toFixed(digits)} ml`;
}

function formatNumber(value, digits = 1) {
  const numberValue = Number(value);
  return Number.isFinite(numberValue) ? numberValue.toFixed(digits) : "--";
}

function formatTime(value) {
  if (!value) {
    return "--";
  }
  return new Date(value).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatEpochTime(value) {
  const numberValue = Number(value);
  if (!Number.isFinite(numberValue) || numberValue <= 0) {
    return "--";
  }
  return new Date(numberValue * 1000).toLocaleTimeString([], {
    hour: "numeric",
    minute: "2-digit",
  });
}

function formatDuration(seconds) {
  const value = Number(seconds);
  if (!Number.isFinite(value) || value < 0) {
    return "--";
  }

  if (value < 60) {
    return `${Math.round(value)} sec`;
  }

  if (value < 3600) {
    return `${Math.round(value / 60)} min`;
  }

  return `${(value / 3600).toFixed(1)} hr`;
}

function buildPairingQrValue(pairing) {
  if (!pairing?.pairing_payload) {
    return "";
  }
  return JSON.stringify(pairing.pairing_payload);
}

export default function Dashboard() {
  const [activeTab, setActiveTab] = useState("monitor");
  const [adminDevices, setAdminDevices] = useState([]);
  const [adminParents, setAdminParents] = useState([]);
  const [adminChildren, setAdminChildren] = useState([]);
  const [ownership, setOwnership] = useState([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState(DEFAULT_DEVICE_ID);
  const [data, setData] = useState([]);
  const [dailyGoalData, setDailyGoalData] = useState([]);
  const [calibration, setCalibration] = useState(null);
  const [pairing, setPairing] = useState(null);
  const [showDebug, setShowDebug] = useState(false);
  const [loading, setLoading] = useState(true);
  const [loadingCalib, setLoadingCalib] = useState(false);
  const [loadingPairing, setLoadingPairing] = useState(false);
  const [error, setError] = useState("");

  const latest = data.length ? data[data.length - 1] : null;
  const selectedAdminDevice = adminDevices.find(
    (item) => item.device?.device_id === selectedDeviceId
  );
  const selectedOnline = Boolean(selectedAdminDevice?.device?.is_online);
  const selectedOfflineSeconds = selectedAdminDevice?.device?.offline_seconds;
  const selectedGraceSeconds = selectedAdminDevice?.device?.offline_grace_seconds;

  const fetchAdminDevices = useCallback(async () => {
    const res = await API.get("admin/devices/");
    const rows = res.data || [];
    setAdminDevices(rows);

    if (!rows.some((item) => item.device?.device_id === selectedDeviceId)) {
      setSelectedDeviceId(rows[0]?.device?.device_id || DEFAULT_DEVICE_ID);
    }
  }, [selectedDeviceId]);

  const fetchAdminManagement = useCallback(async () => {
    const [parentsRes, childrenRes, ownershipRes] = await Promise.all([
      API.get("admin/parents/"),
      API.get("admin/children/"),
      API.get("admin/ownership/"),
    ]);

    setAdminParents(parentsRes.data || []);
    setAdminChildren(childrenRes.data || []);
    setOwnership(ownershipRes.data || []);
  }, []);

  const fetchData = useCallback(async () => {
    const res = await API.get(`data/?device_id=${selectedDeviceId}`);
    const sorted = [...(res.data || [])].sort(
      (a, b) => new Date(a.timestamp) - new Date(b.timestamp)
    );
    setData(sorted);
  }, [selectedDeviceId]);

  const fetchDaily = useCallback(async () => {
    const res = await API.get(`daily-15/?device_id=${selectedDeviceId}`);
    setDailyGoalData(res.data || []);
  }, [selectedDeviceId]);

  const fetchCalibration = useCallback(async () => {
    try {
      const res = await API.get("calibration/");
      setCalibration(res.data);
    } catch {
      setCalibration(null);
    }
  }, []);

  const fetchPairing = useCallback(async () => {
    if (!selectedDeviceId) {
      return;
    }

    try {
      const res = await API.get(`devices/${selectedDeviceId}/pairing/`);
      setPairing(res.data);
    } catch {
      setPairing(null);
    }
  }, [selectedDeviceId]);

  const fetchAll = useCallback(async () => {
    try {
      setLoading(true);
      await Promise.all([
        fetchAdminDevices(),
        fetchData(),
        fetchDaily(),
        fetchCalibration(),
        fetchPairing(),
        fetchAdminManagement(),
      ]);
      setError("");
    } catch (e) {
      setError(e.response?.data?.error || "Dashboard data could not be loaded.");
    } finally {
      setLoading(false);
    }
  }, [fetchAdminDevices, fetchData, fetchDaily, fetchCalibration, fetchPairing, fetchAdminManagement]);

  useEffect(() => {
    fetchAll();
    const interval = setInterval(fetchAll, 3000);
    return () => clearInterval(interval);
  }, [fetchAll]);

  const registerDevice = async () => {
    const input = window.prompt("Device ID", selectedDeviceId || DEFAULT_DEVICE_ID);
    if (!input) {
      return;
    }

    setLoadingPairing(true);
    try {
      const res = await API.post("devices/register/", { device_id: input.trim() });
      setSelectedDeviceId(input.trim());
      setPairing(res.data.pairing);
      await fetchAdminDevices();
    } catch {
      alert("Device registration failed.");
    } finally {
      setLoadingPairing(false);
    }
  };

  const rePairBottle = async () => {
    const input = window.prompt("Device ID to re-pair", selectedDeviceId || DEFAULT_DEVICE_ID);
    if (!input) {
      return;
    }

    setLoadingPairing(true);
    try {
      const res = await API.post("devices/register/", { device_id: input.trim() });
      setSelectedDeviceId(input.trim());
      setPairing(res.data.pairing);
      await fetchAll();
    } catch {
      alert("Could not prepare this bottle for re-pairing.");
    } finally {
      setLoadingPairing(false);
    }
  };

  const refreshPairing = async () => {
    setLoadingPairing(true);
    try {
      await fetchPairing();
    } finally {
      setLoadingPairing(false);
    }
  };

  const regeneratePairing = async () => {
    if (!selectedDeviceId) {
      return;
    }

    if (!window.confirm(`Regenerate QR token for ${selectedDeviceId}? Old QR codes will stop working.`)) {
      return;
    }

    setLoadingPairing(true);
    try {
      const res = await API.post(`admin/devices/${selectedDeviceId}/regenerate-pairing/`);
      setPairing(res.data.pairing);
      await fetchAdminDevices();
    } catch {
      alert("Could not regenerate pairing token.");
    } finally {
      setLoadingPairing(false);
    }
  };

  const unpairDevice = async (deviceId) => {
    if (!window.confirm(`Unpair ${deviceId} from its child and parent?`)) {
      return;
    }

    try {
      const res = await API.post(`admin/devices/${deviceId}/unpair/`);
      if (deviceId === selectedDeviceId) {
        setPairing(res.data.pairing);
      }
      await fetchAll();
    } catch {
      alert("Could not unpair this bottle.");
    }
  };

  const setParentActive = async (parent, isActive) => {
    const action = isActive ? "activate" : "deactivate";
    if (!window.confirm(`Are you sure you want to ${action} ${parent.username}?`)) {
      return;
    }

    try {
      await API.post(`admin/parents/${parent.user_id}/active/`, { is_active: isActive });
      await fetchAdminManagement();
    } catch {
      alert(`Could not ${action} parent.`);
    }
  };

  const resetParentPassword = async (parent) => {
    if (!window.confirm(`Reset password for ${parent.username}? A temporary password will be shown once.`)) {
      return;
    }

    try {
      const res = await API.post(`admin/parents/${parent.user_id}/reset-password/`);
      window.alert(
        `Temporary password for ${res.data.username}:\n\n${res.data.temporary_password}\n\nShare it once and ask the parent to change it.`
      );
    } catch {
      alert("Could not reset parent password.");
    }
  };

  const handleCalibration = async () => {
    if (!window.confirm("Keep the bottle EMPTY and stable before calibration.")) {
      return;
    }

    setLoadingCalib(true);
    try {
      const res = await API.post("calibrate/");
      if (res.data.error) {
        alert(res.data.error);
      } else {
        setCalibration(res.data);
        alert("Calibration successful.");
      }
    } catch {
      alert("Calibration failed. Check Raspberry Pi Flask service.");
    } finally {
      setLoadingCalib(false);
    }
  };

  const resetData = async () => {
    if (!window.confirm(`Clear data for ${selectedDeviceId}?`)) {
      return;
    }

    try {
      await API.delete(`reset/?device_id=${selectedDeviceId}`);
      await fetchAll();
    } catch {
      alert("Reset failed. Login may be required or public reset is disabled.");
    }
  };

  const resetDailyData = async () => {
    if (!window.confirm(`Reset today's fill, drink, and drop history for ${selectedDeviceId}? Calibration is not changed.`)) {
      return;
    }

    try {
      await API.delete(`reset-daily/?device_id=${selectedDeviceId}`);
      await fetchAll();
    } catch {
      alert("Daily reset failed. Check Raspberry Pi service and backend settings.");
    }
  };

  const removeDevice = async () => {
    if (!window.confirm(`Remove ${selectedDeviceId} from dashboard and delete its stored readings?`)) {
      return;
    }

    try {
      await API.delete(`admin/devices/${selectedDeviceId}/remove/`);
      setSelectedDeviceId(DEFAULT_DEVICE_ID);
      await fetchAll();
    } catch {
      alert("Could not remove this bottle.");
    }
  };

  const factoryResetDevice = async () => {
    if (!window.confirm(`Factory reset ${selectedDeviceId}? This clears Pi state, calibration, pairing, and backend readings.`)) {
      return;
    }

    setLoadingPairing(true);
    try {
      const res = await API.post(`admin/devices/${selectedDeviceId}/factory-reset/`);
      setPairing(res.data.pairing);
      await fetchAll();
      alert("Factory reset complete. Calibrate the bottle again, then scan the fresh QR to re-pair.");
    } catch {
      alert("Factory reset failed. Check Raspberry Pi Flask service and backend connection.");
    } finally {
      setLoadingPairing(false);
    }
  };

  const totals = useMemo(() => {
    const active = adminDevices.filter((item) => item.latest);
    const alerts = active.filter((item) => item.latest?.alert);
    const offline = adminDevices.filter((item) => !item.device?.is_online);
    const totalIntake = active.reduce(
      (sum, item) => sum + Number(item.latest?.water_intake || 0),
      0
    );

    return {
      active: active.length,
      alerts: alerts.length,
      offline: offline.length,
      bottles: Math.max(adminDevices.length, active.length),
      totalIntake,
    };
  }, [adminDevices]);

  return (
    <div style={styles.page}>
      <aside style={styles.sidebar}>
        <div style={styles.brandBlock}>
          <div style={styles.logoMark}>jay</div>
          <div>
            <h1 style={styles.brandTitle}>Smart Bottle</h1>
            <p style={styles.brandSub}>Admin Console</p>
          </div>
        </div>

        <button style={styles.primaryButton} onClick={registerDevice}>
          {loadingPairing ? <Spinner /> : "Register / Re-pair"}
        </button>

        <div style={styles.deviceList}>
          {adminDevices.length ? (
            adminDevices.map((item) => (
              <button
                key={item.device.device_id}
                style={{
                  ...styles.deviceItem,
                  ...(selectedDeviceId === item.device.device_id
                    ? styles.deviceItemActive
                    : {}),
                }}
                onClick={() => setSelectedDeviceId(item.device.device_id)}
              >
                <span style={styles.deviceName}>
                  {item.device.name || item.device.device_id}
                </span>
                <span style={styles.deviceMeta}>
                  {item.device.child_name || item.device.device_id}
                  {item.device.school_offline_grace_active ? " | school grace" : ""}
                </span>
                <span style={styles.deviceStatus(item.latest?.alert, item.device?.is_online)}>
                  {item.latest?.alert ? "Alert" : item.device?.is_online ? "Online" : "Offline"}
                </span>
              </button>
            ))
          ) : (
            <div style={styles.emptyBox}>No devices yet. Register bottle_01.</div>
          )}
        </div>
      </aside>

      <main style={styles.main}>
        <header style={styles.header}>
          <div>
            <p style={styles.kicker}>Live Monitoring</p>
            <h2 style={styles.pageTitle}>
              {selectedAdminDevice?.device?.name || selectedDeviceId}
            </h2>
            <p style={styles.subtle}>
              Device ID: <b>{selectedDeviceId}</b> |{" "}
              <b>{selectedOnline ? "Online" : "Offline"}</b>
            </p>
          </div>
          <div style={styles.headerActions}>
            <button style={styles.secondaryButton} onClick={fetchAll}>
              Refresh
            </button>
            <button style={styles.dangerButton} onClick={resetData}>
              Reset Bottle Data
            </button>
            <button style={styles.warningButton} onClick={resetDailyData}>
              Reset Today
            </button>
            <button style={styles.dangerButton} onClick={removeDevice}>
              Remove Bottle
            </button>
            <button style={styles.dangerButton} onClick={factoryResetDevice}>
              Factory Reset
            </button>
          </div>
        </header>

        {error && <div style={styles.errorBanner}>{error}</div>}

        <section style={styles.connectionBanner(selectedOnline)}>
          <div style={styles.connectionLeft}>
            <span style={styles.connectionDot(selectedOnline)} />
            <div>
              <h3 style={styles.connectionTitle}>
                Smart bottle is {selectedOnline ? "online" : "offline"}
              </h3>
              <p style={styles.connectionText}>
                {selectedOnline
                  ? `Last heartbeat ${formatDuration(selectedOfflineSeconds)} ago. Data is updating normally.`
                  : `Last seen ${formatTime(selectedAdminDevice?.device?.last_seen)}. Check Raspberry Pi power, Wi-Fi, or backend URL.`}
              </p>
            </div>
          </div>
          <div style={styles.connectionStats}>
            <span>Grace: {formatDuration(selectedGraceSeconds)}</span>
            <span>
              {selectedAdminDevice?.device?.school_offline_grace_active
                ? "School mode grace active"
                : "Normal monitoring"}
            </span>
          </div>
        </section>

        <nav style={styles.tabs}>
          {[
            ["monitor", "Bottle Monitor"],
            ["ownership", "Ownership"],
            ["parents", "Parents"],
            ["children", "Children"],
          ].map(([key, label]) => (
            <button
              key={key}
              style={{
                ...styles.tabButton,
                ...(activeTab === key ? styles.tabButtonActive : {}),
              }}
              onClick={() => setActiveTab(key)}
            >
              {label}
            </button>
          ))}
        </nav>

        <section style={styles.summaryGrid}>
          <SummaryCard title="Bottles" value={totals.bottles} caption="registered or seen" />
          <SummaryCard title="Active Streams" value={totals.active} caption="sending data" />
          <SummaryCard title="Offline" value={totals.offline} caption="needs network check" tone={totals.offline ? "warn" : "ok"} />
          <SummaryCard title="Alerts" value={totals.alerts} caption="needs attention" tone={totals.alerts ? "warn" : "ok"} />
          <SummaryCard title="Total Intake" value={formatMl(totals.totalIntake)} caption="latest all bottles" />
          <SummaryCard title="Health" value={`${formatNumber(latest?.sensor_health, 0)}%`} caption={latest?.movement_state || "movement"} tone={Number(latest?.sensor_health || 0) < 70 ? "warn" : "ok"} />
        </section>

        {activeTab === "monitor" && (
          <MonitorTab
            latest={latest}
            loading={loading}
            data={data}
            dailyGoalData={dailyGoalData}
            pairing={pairing}
            selectedDeviceId={selectedDeviceId}
            loadingPairing={loadingPairing}
            refreshPairing={refreshPairing}
            regeneratePairing={regeneratePairing}
            registerDevice={rePairBottle}
            loadingCalib={loadingCalib}
            handleCalibration={handleCalibration}
            showDebug={showDebug}
            setShowDebug={setShowDebug}
            calibration={calibration}
          />
        )}

        {activeTab === "ownership" && (
          <OwnershipTab
            rows={ownership}
            onSelectBottle={setSelectedDeviceId}
            unpairDevice={unpairDevice}
          />
        )}

        {activeTab === "parents" && (
          <ParentsTab
            parents={adminParents}
            ownership={ownership}
            setParentActive={setParentActive}
            resetParentPassword={resetParentPassword}
          />
        )}

        {activeTab === "children" && (
          <ChildrenTab children={adminChildren} onSelectBottle={setSelectedDeviceId} />
        )}
      </main>
    </div>
  );
}

function MonitorTab({
  latest,
  loading,
  data,
  dailyGoalData,
  pairing,
  selectedDeviceId,
  loadingPairing,
  refreshPairing,
  regeneratePairing,
  registerDevice,
  loadingCalib,
  handleCalibration,
  showDebug,
  setShowDebug,
  calibration,
}) {
  return (
    <section style={styles.contentGrid}>
      <div style={styles.panel}>
        <PanelHeader title="Bottle Status" caption="current balance and goal progress" />
        <BottleStatus latest={latest} loading={loading} />
      </div>

      <div style={styles.panel}>
        <PanelHeader title="Pairing QR" caption="scan from parent mobile app" />
        <PairingPanel
          pairing={pairing}
          selectedDeviceId={selectedDeviceId}
          loading={loadingPairing}
          refreshPairing={refreshPairing}
          regeneratePairing={regeneratePairing}
          registerDevice={registerDevice}
        />
      </div>

      <div style={styles.panelWide}>
        <PanelHeader title="Intake Trend" caption="water intake compared with dynamic goal" />
        <TrendChart data={data} />
      </div>

      <div style={styles.panel}>
        <PanelHeader title="Controls" caption="calibration and diagnostics" />
        <div style={styles.controlStack}>
          <button
            style={styles.primaryButton}
            disabled={loadingCalib}
            onClick={handleCalibration}
          >
            {loadingCalib ? <Spinner /> : "Calibrate Empty Bottle"}
          </button>
          <button
            style={styles.secondaryButton}
            onClick={() => setShowDebug((value) => !value)}
          >
            {showDebug ? "Hide Sensor Debug" : "Show Sensor Debug"}
          </button>
          <InfoLine label="Empty distance" value={`${calibration?.empty_dist ?? "--"} cm`} />
          <InfoLine label="Raw empty" value={`${calibration?.raw_empty_dist ?? "--"} cm`} />
          <InfoLine label="Offset" value={`${calibration?.distance_offset ?? "--"} cm`} />
        </div>
      </div>

      <div style={styles.panelWide}>
        <PanelHeader title="Recent Events" caption="fill, drink, and drop history" />
        <EventHistory data={data} />
      </div>

      <div style={styles.panelWide}>
        <PanelHeader title="15-Day Goal Completion" caption="green days completed, red days missed" />
        <DailyGoalChart data={dailyGoalData} />
      </div>

      {showDebug && latest && (
        <div style={styles.panelWide}>
          <PanelHeader title="Sensor Debug" caption="VL53L0X and MPU6050 diagnostics" />
          <DebugPanel latest={latest} />
        </div>
      )}
    </section>
  );
}

function PanelHeader({ title, caption }) {
  return (
    <div style={styles.panelHeader}>
      <h3>{title}</h3>
      <p>{caption}</p>
    </div>
  );
}

function SummaryCard({ title, value, caption, tone }) {
  return (
    <div style={{ ...styles.summaryCard, ...(tone === "warn" ? styles.summaryWarn : {}) }}>
      <p>{title}</p>
      <h3>{value}</h3>
      <span>{caption}</span>
    </div>
  );
}

function BottleStatus({ latest, loading }) {
  if (loading && !latest) {
    return <div style={styles.emptyBox}>Loading bottle data...</div>;
  }

  if (!latest) {
    return <div style={styles.emptyBox}>No readings received for this bottle yet.</div>;
  }

  const waterIntake = Number(latest.water_intake || 0);
  const goal = Number(latest.goal || 4000);
  const balance = Number(latest.balance_ml ?? latest.water_ml ?? 0);
  const percent = Number(latest.bottle_level || latest.percent || 0);
  const progress = Math.min(100, goal ? (waterIntake / goal) * 100 : 0);

  return (
    <div style={styles.bottleStatus}>
      <Bottle level={percent} />
      <div style={styles.statusDetails}>
        <div style={styles.bigMetric}>{formatMl(waterIntake)}</div>
        <div style={styles.subtle}>Daily intake</div>
        <div style={styles.progressTrack}>
          <div style={{ ...styles.progressFill, width: `${progress}%` }} />
        </div>
        <div style={styles.metricGrid}>
          <Metric label="Goal" value={formatMl(goal)} />
          <Metric label="Balance" value={formatMl(balance, 1)} />
          <Metric label="Filled" value={formatMl(latest.total_filled, 1)} />
          <Metric label="Dropped" value={formatMl(latest.total_dropped, 1)} />
          <Metric label="Temp" value={`${latest.temperature ?? "--"} C`} />
          <Metric label="Humidity" value={`${latest.humidity ?? "--"}%`} />
          <Metric label="Movement" value={latest.movement_state || "--"} />
          <Metric label="Health" value={`${formatNumber(latest.sensor_health, 0)}%`} />
        </div>
        <div style={styles.eventBadge(latest.event)}>{latest.event || "NORMAL"}</div>
        {latest.alert && <div style={styles.alertBox}>{latest.alert}</div>}
        <div style={styles.reminderText}>
          Last drink: {formatEpochTime(latest.last_drink_time)} | Next reminder:{" "}
          {formatEpochTime(latest.next_reminder_time)}
        </div>
      </div>
    </div>
  );
}

function Metric({ label, value }) {
  return (
    <div style={styles.metricItem}>
      <span>{label}</span>
      <b>{value}</b>
    </div>
  );
}

function PairingPanel({
  pairing,
  selectedDeviceId,
  loading,
  refreshPairing,
  regeneratePairing,
  registerDevice,
}) {
  const qrValue = buildPairingQrValue(pairing);
  const token = pairing?.pairing_payload?.pairing_token || "";

  return (
    <div style={styles.pairingLayout}>
      <div style={styles.qrBox}>
        {qrValue ? (
          <QRCodeSVG value={qrValue} size={176} level="M" includeMargin />
        ) : (
          <div style={styles.emptyQr}>No QR</div>
        )}
      </div>
      <div style={styles.pairingDetails}>
        <InfoLine label="Device ID" value={selectedDeviceId || "--"} />
        <InfoLine label="Pairing token" value={token || "--"} mono />
        <p style={styles.subtle}>
          Open the mobile app, login as parent, press QR scan, and scan this code.
        </p>
        <div style={styles.inlineActions}>
          <button style={styles.secondaryButton} onClick={refreshPairing}>
            {loading ? <Spinner /> : "Reload QR"}
          </button>
          <button style={styles.warningButton} onClick={regeneratePairing}>
            Regenerate QR
          </button>
          <button style={styles.primaryButton} onClick={registerDevice}>
            Register Again
          </button>
        </div>
      </div>
    </div>
  );
}

function OwnershipTab({ rows, onSelectBottle, unpairDevice }) {
  return (
    <section style={styles.panelWide}>
      <PanelHeader
        title="Bottle Ownership"
        caption="which parent and child are connected with each smart bottle"
      />
      <AdminTable
        emptyText="No paired bottle ownership records yet."
        columns={[
          "Bottle ID",
          "Child",
          "Parent",
          "Email",
          "Phone",
          "Status",
          "Balance",
          "Alert",
          "Actions",
        ]}
      >
        {rows.map((row) => (
          <tr key={row.device_id}>
            <td><b>{row.device_id}</b></td>
            <td>{row.child_name || "--"}<SmallText>{row.school_name || ""}</SmallText></td>
            <td>{row.parent_username || "--"}</td>
            <td>{row.parent_email || "--"}</td>
            <td>{row.parent_phone || "--"}</td>
            <td>
              <span style={styles.statusPill(row.is_online)}>
                {row.is_online ? "Online" : "Offline"}
              </span>
            </td>
            <td>{formatMl(row.latest?.balance_ml ?? row.latest?.water_ml, 1)}</td>
            <td>{row.latest?.alert || "OK"}</td>
            <td>
              <div style={styles.rowActions}>
                <button style={styles.smallButton} onClick={() => onSelectBottle(row.device_id)}>
                  Open
                </button>
                <button style={styles.smallDangerButton} onClick={() => unpairDevice(row.device_id)}>
                  Unpair
                </button>
              </div>
            </td>
          </tr>
        ))}
      </AdminTable>
    </section>
  );
}

function ParentsTab({ parents, ownership, setParentActive, resetParentPassword }) {
  return (
    <section style={styles.contentGrid}>
      <div style={styles.panelWide}>
        <PanelHeader
          title="Registered Parents"
          caption="parent contact details and account status"
        />
        <div style={styles.securityNote}>
          Passwords cannot be shown because Django stores only protected password hashes.
          Use a password reset flow for account recovery.
        </div>
        <AdminTable
          emptyText="No parents registered yet."
          columns={[
            "Username",
            "Email",
            "Phone",
            "Children",
            "Bottles",
            "Status",
            "Password",
            "Actions",
          ]}
        >
          {parents.map((parent) => (
            <tr key={parent.id}>
              <td><b>{parent.username}</b></td>
              <td>{parent.email || "--"}</td>
              <td>{parent.phone || "--"}</td>
              <td>{parent.children_count}</td>
              <td>{parent.bottle_count}</td>
              <td>{parent.is_active ? "Active" : "Disabled"}</td>
              <td>Not viewable</td>
              <td>
                <div style={styles.rowActions}>
                  <button
                    style={parent.is_active ? styles.smallDangerButton : styles.smallButton}
                    onClick={() => setParentActive(parent, !parent.is_active)}
                  >
                    {parent.is_active ? "Deactivate" : "Activate"}
                  </button>
                  <button
                    style={styles.smallButton}
                    onClick={() => resetParentPassword(parent)}
                  >
                    Reset Password
                  </button>
                </div>
              </td>
            </tr>
          ))}
        </AdminTable>
      </div>

      <div style={styles.panelWide}>
        <PanelHeader
          title="Parent Bottle Mapping"
          caption="quick view of parent, child, and assigned device"
        />
        <AdminTable
          emptyText="No mapping data yet."
          columns={["Parent", "Child", "Bottle", "Status", "Latest Intake", "Latest Alert"]}
        >
          {ownership.map((row) => (
            <tr key={`${row.parent_username}-${row.child_name}-${row.device_id}`}>
              <td>{row.parent_username || "--"}</td>
              <td>{row.child_name || "--"}</td>
              <td><b>{row.device_id}</b></td>
              <td>{row.is_online ? "Online" : "Offline"}</td>
              <td>{formatMl(row.latest?.water_intake, 1)}</td>
              <td>{row.latest?.alert || "OK"}</td>
            </tr>
          ))}
        </AdminTable>
      </div>
    </section>
  );
}

function ChildrenTab({ children, onSelectBottle }) {
  return (
    <section style={styles.panelWide}>
      <PanelHeader
        title="Children"
        caption="school child profiles and assigned smart bottles"
      />
      <AdminTable
        emptyText="No child profiles registered yet."
        columns={[
          "Child",
          "Age",
          "Health",
          "School",
          "Parent",
          "Email",
          "Goals",
          "Bottles",
        ]}
      >
        {children.map((child) => (
          <tr key={child.id}>
            <td><b>{child.name}</b></td>
            <td>{child.age ?? "--"}</td>
            <td>
              {child.weight_kg ? `${child.weight_kg} kg` : "--"}
              <SmallText>{`${child.activity_level || "normal"} activity${child.heat_sensitivity ? " | heat sensitive" : ""}`}</SmallText>
            </td>
            <td>
              {child.school_name || "--"}
              <SmallText>
                {child.school_mode_enabled ? `${child.school_start} - ${child.school_end}` : "School mode off"}
              </SmallText>
            </td>
            <td>{child.parent_username}</td>
            <td>{child.parent_email || "--"}</td>
            <td>
              {formatMl(child.daily_goal_ml)}
              <SmallText>{`Suggested ${formatMl(child.recommended_goal_ml)}`}</SmallText>
            </td>
            <td>
              {child.bottles?.length ? (
                <div style={styles.tagList}>
                  {child.bottles.map((bottle) => (
                    <button
                      key={bottle.device_id}
                      style={styles.tagButton}
                      onClick={() => onSelectBottle(bottle.device_id)}
                    >
                      {bottle.device_id}
                    </button>
                  ))}
                </div>
              ) : (
                "--"
              )}
            </td>
          </tr>
        ))}
      </AdminTable>
    </section>
  );
}

function AdminTable({ columns, children, emptyText }) {
  const rows = React.Children.toArray(children).filter(Boolean);

  if (!rows.length) {
    return <div style={styles.emptyBox}>{emptyText}</div>;
  }

  return (
    <div style={styles.tableWrap}>
      <table style={styles.table}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column} style={styles.tableHeader}>{column}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) =>
            React.cloneElement(row, {
              children: React.Children.map(row.props.children, (cell) =>
                React.isValidElement(cell)
                  ? React.cloneElement(cell, {
                      style: { ...styles.tableCell, ...(cell.props.style || {}) },
                    })
                  : cell
              ),
            })
          )}
        </tbody>
      </table>
    </div>
  );
}

function SmallText({ children }) {
  if (!children) {
    return null;
  }

  return <span style={styles.smallText}>{children}</span>;
}

function InfoLine({ label, value, mono }) {
  return (
    <div style={styles.infoLine}>
      <span>{label}</span>
      <b style={mono ? styles.monoValue : undefined}>{value}</b>
    </div>
  );
}

function TrendChart({ data }) {
  if (!data.length) {
    return <div style={styles.emptyBox}>No trend data yet.</div>;
  }

  return (
    <ResponsiveContainer width="100%" height={280}>
      <AreaChart data={data}>
        <CartesianGrid stroke="#e5e7eb" />
        <XAxis
          dataKey="timestamp"
          tickFormatter={(value) => new Date(value).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" })}
        />
        <YAxis />
        <Tooltip
          labelFormatter={(value) => new Date(value).toLocaleString()}
          formatter={(value, name) => [formatMl(value, 1), name === "water_intake" ? "Intake" : "Goal"]}
        />
        <Area type="monotone" dataKey="water_intake" stroke="#2563eb" fill="#bfdbfe" strokeWidth={3} />
        <Area type="monotone" dataKey="goal" stroke="#ef4444" fill="transparent" strokeDasharray="5 5" />
      </AreaChart>
    </ResponsiveContainer>
  );
}

function DailyGoalChart({ data }) {
  if (!data.length) {
    return <div style={styles.emptyBox}>No daily goal data yet.</div>;
  }

  return (
    <>
      <ResponsiveContainer width="100%" height={260}>
        <BarChart data={data}>
          <CartesianGrid stroke="#e5e7eb" />
          <XAxis dataKey="label" />
          <YAxis />
          <Tooltip
            formatter={(value, name) => [
              formatMl(value, 1),
              name === "water_intake" ? "Intake" : "Goal",
            ]}
          />
          <Bar dataKey="goal" fill="#e5e7eb" />
          <Bar
            dataKey="water_intake"
            shape={(props) => {
              const item = data[props.index];
              return <rect {...props} fill={item?.completed ? "#16a34a" : "#dc2626"} rx={4} />;
            }}
          />
        </BarChart>
      </ResponsiveContainer>
      <div style={styles.legend}>
        <span><b style={{ color: "#16a34a" }}>Green</b> complete</span>
        <span><b style={{ color: "#dc2626" }}>Red</b> incomplete</span>
      </div>
    </>
  );
}

function EventHistory({ data }) {
  const events = data
    .filter((item) => ["FILL", "DRINK", "DROP"].includes(item.event))
    .slice(-10)
    .reverse();

  if (!events.length) {
    return <div style={styles.emptyBox}>No fill, drink, or drop events yet.</div>;
  }

  return (
    <div style={styles.tableWrap}>
      <table style={styles.table}>
        <thead>
          <tr>
            <th>Time</th>
            <th>Event</th>
            <th>Amount</th>
            <th>Balance</th>
            <th>Direction</th>
          </tr>
        </thead>
        <tbody>
          {events.map((item) => (
            <tr key={item.id || item.timestamp}>
              <td>{formatTime(item.timestamp)}</td>
              <td><span style={styles.tableEvent(item.event)}>{item.event}</span></td>
              <td>{formatMl(item.event_amount, 1)}</td>
              <td>{formatMl(item.balance_ml ?? item.water_ml, 1)}</td>
              <td>{item.direction || "NORMAL"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DebugPanel({ latest }) {
  const items = [
    ["Raw Current", `${formatNumber(latest.raw_current_dist, 3)} cm`],
    ["Corrected", `${formatNumber(latest.corrected_current_dist, 3)} cm`],
    ["Water Height", `${formatNumber(latest.water_height, 3)} cm`],
    ["Offset", `${formatNumber(latest.distance_offset, 3)} cm`],
    ["Raw Empty", `${formatNumber(latest.raw_empty_dist, 3)} cm`],
    ["Pitch", `${formatNumber(latest.pitch, 2)} deg`],
    ["Roll", `${formatNumber(latest.roll, 2)} deg`],
    ["Movement", latest.movement_state || "--"],
    ["Direction", latest.direction || "--"],
    ["Sensor Health", `${formatNumber(latest.sensor_health, 1)}%`],
    ["TOF Valid", `${formatNumber(latest.tof_valid_percent, 1)}%`],
    ["MPU Stability", `${formatNumber(latest.mpu_stability, 1)}%`],
    ["DHT", latest.dht_status || "--"],
    ["Drop Latch", latest.drop_latch_active ? "Active" : "Off"],
    ["Latch Dir", latest.drop_latch_direction || "--"],
    ["Cal Points", latest.calibration_points_count ?? 0],
    ["Reminder", `${formatNumber(latest.reminder_interval_seconds, 0)} sec`],
  ];

  return (
    <div style={styles.debugGrid}>
      {items.map(([label, value]) => (
        <div key={label} style={styles.debugItem}>
          <span>{label}</span>
          <b>{value}</b>
        </div>
      ))}
    </div>
  );
}

const styles = {
  page: {
    minHeight: "100vh",
    display: "grid",
    gridTemplateColumns: "280px 1fr",
    background: "#f4f7fb",
    color: "#0f172a",
    fontFamily: "Inter, Segoe UI, Arial, sans-serif",
  },
  sidebar: {
    background: "#ffffff",
    borderRight: "1px solid #e5e7eb",
    padding: "22px",
    position: "sticky",
    top: 0,
    height: "100vh",
    overflowY: "auto",
  },
  brandBlock: {
    display: "flex",
    alignItems: "center",
    gap: "12px",
    marginBottom: "22px",
  },
  logoMark: {
    width: "42px",
    height: "42px",
    borderRadius: "8px",
    display: "grid",
    placeItems: "center",
    background: "#2563eb",
    color: "#fff",
    fontWeight: 900,
  },
  brandTitle: { margin: 0, fontSize: "20px" },
  brandSub: { margin: "2px 0 0", color: "#64748b", fontSize: "13px" },
  deviceList: { display: "flex", flexDirection: "column", gap: "8px", marginTop: "18px" },
  deviceItem: {
    textAlign: "left",
    background: "#f8fafc",
    border: "1px solid #e5e7eb",
    borderRadius: "8px",
    padding: "12px",
    cursor: "pointer",
  },
  deviceItemActive: {
    background: "#eff6ff",
    borderColor: "#2563eb",
  },
  deviceName: { display: "block", fontWeight: 800, color: "#0f172a" },
  deviceMeta: { display: "block", color: "#64748b", fontSize: "12px", marginTop: "3px" },
  deviceStatus: (alert, online) => ({
    display: "inline-block",
    marginTop: "8px",
    padding: "3px 8px",
    borderRadius: "999px",
    color: alert ? "#991b1b" : online ? "#166534" : "#92400e",
    background: alert ? "#fee2e2" : online ? "#dcfce7" : "#fef3c7",
    fontSize: "12px",
    fontWeight: 800,
  }),
  main: { padding: "24px", minWidth: 0 },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: "16px",
    marginBottom: "18px",
  },
  headerActions: { display: "flex", gap: "10px", flexWrap: "wrap" },
  tabs: {
    display: "flex",
    gap: "8px",
    flexWrap: "wrap",
    marginBottom: "16px",
  },
  tabButton: {
    border: "1px solid #cbd5e1",
    background: "#fff",
    color: "#334155",
    padding: "10px 12px",
    borderRadius: "8px",
    fontWeight: 800,
    cursor: "pointer",
  },
  tabButtonActive: {
    background: "#2563eb",
    color: "#fff",
    borderColor: "#2563eb",
  },
  kicker: { margin: 0, color: "#2563eb", fontWeight: 800, fontSize: "13px" },
  pageTitle: { margin: "4px 0", fontSize: "30px" },
  subtle: { color: "#64748b", margin: 0, lineHeight: 1.5 },
  connectionBanner: (online) => ({
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: "14px",
    border: `1px solid ${online ? "#bbf7d0" : "#fecaca"}`,
    background: online ? "#f0fdf4" : "#fff1f2",
    borderRadius: "8px",
    padding: "14px 16px",
    marginBottom: "16px",
  }),
  connectionLeft: { display: "flex", alignItems: "center", gap: "12px", minWidth: 0 },
  connectionDot: (online) => ({
    width: "14px",
    height: "14px",
    borderRadius: "50%",
    background: online ? "#22c55e" : "#ef4444",
    boxShadow: online ? "0 0 0 6px rgba(34,197,94,0.14)" : "0 0 0 6px rgba(239,68,68,0.12)",
    flex: "0 0 auto",
  }),
  connectionTitle: { margin: 0, fontSize: "16px", fontWeight: 900 },
  connectionText: { margin: "3px 0 0", color: "#475569", lineHeight: 1.45 },
  connectionStats: {
    display: "flex",
    flexDirection: "column",
    alignItems: "flex-end",
    gap: "4px",
    color: "#475569",
    fontSize: "13px",
    fontWeight: 800,
    whiteSpace: "nowrap",
  },
  summaryGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(auto-fit, minmax(130px, 1fr))",
    gap: "12px",
    marginBottom: "16px",
  },
  summaryCard: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: "8px",
    padding: "14px",
  },
  summaryWarn: { borderColor: "#f59e0b", background: "#fffbeb" },
  contentGrid: {
    display: "grid",
    gridTemplateColumns: "minmax(280px, 0.9fr) minmax(340px, 1.1fr)",
    gap: "16px",
  },
  panel: {
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: "8px",
    padding: "16px",
    minWidth: 0,
  },
  panelWide: {
    gridColumn: "1 / -1",
    background: "#fff",
    border: "1px solid #e5e7eb",
    borderRadius: "8px",
    padding: "16px",
    minWidth: 0,
  },
  panelHeader: { marginBottom: "12px" },
  bottleStatus: {
    display: "grid",
    gridTemplateColumns: "150px 1fr",
    alignItems: "center",
    gap: "18px",
  },
  statusDetails: { minWidth: 0 },
  bigMetric: { fontSize: "34px", fontWeight: 900 },
  progressTrack: {
    height: "10px",
    background: "#e5e7eb",
    borderRadius: "999px",
    overflow: "hidden",
    margin: "12px 0",
  },
  progressFill: { height: "100%", background: "#22c55e" },
  metricGrid: { display: "grid", gridTemplateColumns: "repeat(2, minmax(0, 1fr))", gap: "8px" },
  metricItem: { background: "#f8fafc", borderRadius: "8px", padding: "9px" },
  eventBadge: (event) => ({
    marginTop: "10px",
    display: "inline-block",
    padding: "7px 10px",
    borderRadius: "999px",
    fontWeight: 900,
    background:
      event === "DROP" ? "#fee2e2" : event === "DRINK" ? "#dcfce7" : event === "FILL" ? "#dbeafe" : "#f1f5f9",
  }),
  alertBox: { marginTop: "10px", background: "#fef3c7", color: "#92400e", borderRadius: "8px", padding: "9px", fontWeight: 800 },
  reminderText: { marginTop: "10px", color: "#64748b", fontSize: "13px" },
  pairingLayout: { display: "grid", gridTemplateColumns: "210px 1fr", gap: "16px", alignItems: "center" },
  qrBox: { border: "1px solid #e5e7eb", borderRadius: "8px", padding: "12px", display: "grid", placeItems: "center", background: "#fff" },
  emptyQr: { width: "176px", height: "176px", display: "grid", placeItems: "center", background: "#f1f5f9", color: "#64748b" },
  pairingDetails: { display: "flex", flexDirection: "column", gap: "9px" },
  infoLine: { display: "grid", gridTemplateColumns: "120px 1fr", gap: "10px", alignItems: "start" },
  monoValue: { fontFamily: "Consolas, monospace", wordBreak: "break-all" },
  inlineActions: { display: "flex", gap: "10px", flexWrap: "wrap" },
  controlStack: { display: "flex", flexDirection: "column", gap: "10px" },
  primaryButton: { border: 0, borderRadius: "8px", background: "#2563eb", color: "#fff", padding: "10px 12px", fontWeight: 800, cursor: "pointer" },
  secondaryButton: { border: "1px solid #cbd5e1", borderRadius: "8px", background: "#fff", color: "#0f172a", padding: "10px 12px", fontWeight: 800, cursor: "pointer" },
  warningButton: { border: 0, borderRadius: "8px", background: "#f59e0b", color: "#111827", padding: "10px 12px", fontWeight: 800, cursor: "pointer" },
  dangerButton: { border: 0, borderRadius: "8px", background: "#dc2626", color: "#fff", padding: "10px 12px", fontWeight: 800, cursor: "pointer" },
  errorBanner: { background: "#fee2e2", color: "#991b1b", padding: "12px", borderRadius: "8px", marginBottom: "14px", fontWeight: 800 },
  securityNote: {
    background: "#eff6ff",
    color: "#1e3a8a",
    padding: "10px 12px",
    borderRadius: "8px",
    marginBottom: "12px",
    fontWeight: 700,
  },
  emptyBox: { background: "#f8fafc", color: "#64748b", borderRadius: "8px", padding: "18px", textAlign: "center" },
  tableWrap: { overflowX: "auto" },
  table: { width: "100%", borderCollapse: "collapse" },
  tableHeader: {
    textAlign: "left",
    padding: "10px",
    background: "#f1f5f9",
    borderBottom: "1px solid #e5e7eb",
    color: "#475569",
    fontSize: "13px",
  },
  tableCell: {
    padding: "10px",
    borderBottom: "1px solid #e5e7eb",
    verticalAlign: "top",
  },
  smallText: { display: "block", color: "#64748b", fontSize: "12px", marginTop: "3px" },
  statusPill: (online) => ({
    display: "inline-block",
    padding: "4px 8px",
    borderRadius: "999px",
    background: online ? "#dcfce7" : "#fef3c7",
    color: online ? "#166534" : "#92400e",
    fontWeight: 900,
    fontSize: "12px",
  }),
  smallButton: {
    border: "1px solid #cbd5e1",
    background: "#fff",
    borderRadius: "7px",
    padding: "7px 10px",
    cursor: "pointer",
    fontWeight: 800,
  },
  smallDangerButton: {
    border: 0,
    background: "#fee2e2",
    color: "#991b1b",
    borderRadius: "7px",
    padding: "7px 10px",
    cursor: "pointer",
    fontWeight: 800,
  },
  rowActions: { display: "flex", gap: "6px", flexWrap: "wrap" },
  tagList: { display: "flex", flexWrap: "wrap", gap: "6px" },
  tagButton: {
    border: 0,
    background: "#dbeafe",
    color: "#1d4ed8",
    borderRadius: "999px",
    padding: "5px 9px",
    cursor: "pointer",
    fontWeight: 800,
  },
  tableEvent: (event) => ({
    fontWeight: 900,
    color: event === "DROP" ? "#dc2626" : event === "DRINK" ? "#15803d" : "#2563eb",
  }),
  legend: { display: "flex", gap: "14px", color: "#64748b", fontSize: "13px" },
  debugGrid: { display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))", gap: "10px" },
  debugItem: { background: "#f8fafc", borderRadius: "8px", padding: "10px" },
  spinner: {
    width: "14px",
    height: "14px",
    border: "3px solid rgba(255,255,255,0.65)",
    borderTop: "3px solid transparent",
    borderRadius: "50%",
    display: "inline-block",
  },
};
