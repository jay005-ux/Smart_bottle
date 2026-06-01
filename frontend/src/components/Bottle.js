import React from "react";

export default function Bottle({ level }) {
  return (
    <div style={styles.container}>
      <div style={styles.bottle}>
        
        {/* Water */}
        <div
          style={{
            ...styles.water,
            height: `${level}%`,
          }}
        >
          {/* SVG Wave */}
          <svg
            viewBox="0 0 500 150"
            preserveAspectRatio="none"
            style={styles.wave}
          >
            <path
              d="M0.00,49.98 C150.00,150.00 349.21,-50.00 500.00,49.98 L500.00,150.00 L0.00,150.00 Z"
              style={{ fill: "#00bfff" }}
            ></path>
          </svg>
        </div>

      </div>

      <p style={{ marginTop: "10px" }}>{level.toFixed(1)}%</p>
    </div>
  );
}

const styles = {
  container: {
    textAlign: "center",
  },

  bottle: {
    width: "120px",
    height: "300px",
    border: "4px solid #333",
    borderRadius: "20px",
    position: "relative",
    overflow: "hidden",
    margin: "auto",
    background: "#f0f0f0",
  },

  water: {
    position: "absolute",
    bottom: 0,
    width: "100%",
    background: "linear-gradient(to top, #00bfff, #1e90ff)",
    transition: "height 1s ease-in-out",
    overflow: "hidden",
  },

  wave: {
    position: "absolute",
    width: "200%",
    height: "100%",
    bottom: 0,
    left: 0,
    animation: "waveMove 2s linear infinite",
  },
};