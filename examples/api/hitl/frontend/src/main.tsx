import React from "react";
import { createRoot } from "react-dom/client";

import App from "./App.tsx";
import "./styles.css";

const container = document.getElementById("root");
if (!container) throw new Error('index.html must contain <div id="root">.');

createRoot(container).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
