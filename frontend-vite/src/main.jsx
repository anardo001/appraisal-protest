
/**
 * main.jsx — Vite entry point
 * Mounts the React app into #root. CSS imported here so Vite bundles it.
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App.jsx";

createRoot(document.getElementById("root")).render(
  <StrictMode>
    <App />
  </StrictMode>
);
