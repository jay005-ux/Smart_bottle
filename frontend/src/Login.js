import React, { useState } from "react";

export default function Login({ setAuth }) {
  const [user, setUser] = useState("");
  const [pass, setPass] = useState("");

  const login = () => {
    if (user === "parent" && pass === "1234") {
      localStorage.setItem("auth", "true");
      setAuth(true);
    } else {
      alert("Wrong username or password");
    }
  };

  return (
    <div style={styles.container}>
      <h2>🔐 Parent Login</h2>

      <input
        style={styles.input}
        placeholder="Username"
        onChange={(e) => setUser(e.target.value)}
      />

      <input
        style={styles.input}
        type="password"
        placeholder="Password"
        onChange={(e) => setPass(e.target.value)}
      />

      <button style={styles.button} onClick={login}>
        Login
      </button>
    </div>
  );
}

const styles = {
  container: {
    display: "flex",
    flexDirection: "column",
    width: "300px",
    margin: "100px auto",
    gap: "10px",
    textAlign: "center",
  },
  input: {
    padding: "10px",
    fontSize: "16px",
  },
  button: {
    padding: "10px",
    background: "#007bff",
    color: "white",
    border: "none",
    cursor: "pointer",
  },
};