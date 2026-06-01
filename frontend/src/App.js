import React, { useState } from "react";
import Login from "./Login";
import Dashboard from "./Dashboard";

function App() {
  const [auth, setAuth] = useState(localStorage.getItem("auth"));

  return auth ? <Dashboard setAuth={setAuth} /> : <Login setAuth={setAuth} />;
}

export default App;