import { Navigate, Route, Routes } from "react-router-dom";
import { Layout } from "./components/Layout";
import { Guard, Login } from "./pages/Login";
import { Dashboard } from "./pages/Dashboard";
import { StackPage } from "./pages/StackPage";
import { Activity } from "./pages/Activity";
import { Templates } from "./pages/Templates";
import { Mail } from "./pages/Mail";
import { Settings } from "./pages/Settings";
import { PanelProvider } from "./panel";

export function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <Guard>
            <PanelProvider>
              <Layout />
            </PanelProvider>
          </Guard>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="stacks/:name" element={<StackPage />} />
        <Route path="activity" element={<Activity />} />
        <Route path="templates" element={<Templates />} />
        <Route path="mail" element={<Mail />} />
        <Route path="settings" element={<Settings />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
