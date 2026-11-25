import { Navigate, Route, Routes } from "react-router-dom";
import ProtectedRoute from "./components/ProtectedRoute";
import RoleLayout from "./components/RoleLayout";
import { getDefaultRouteForRole, useAuth } from "./context/AuthContext";
import AdminOutletsPage from "./pages/AdminOutletsPage";
import CounterScanner from "./pages/CounterScanner";
import ForgotPasswordPage from "./pages/ForgotPasswordPage";
import LoginPage from "./pages/LoginPage";
import ManagerDashboard from "./pages/ManagerDashboard";
import OutletManagerDashboard from "./pages/OutletManagerDashboard";
import RegisterOrganisationPage from "./pages/RegisterOrganisationPage";
import RegisterPage from "./pages/RegisterPage";
import ResetPasswordPage from "./pages/ResetPasswordPage";
import StudentPortal from "./pages/StudentPortal";

function RootRedirect() {
  const { user, authLoading } = useAuth();
  if (authLoading) {
    return (
      <div className="min-h-screen bg-navy-950 text-slate-100 flex items-center justify-center p-6">
        <div className="rounded-2xl border border-slate-800 bg-navy-900/80 px-6 py-5 text-sm text-slate-300">
          Checking session...
        </div>
      </div>
    );
  }
  if (!user) {
    return <Navigate to="/login" replace />;
  }
  return <Navigate to={getDefaultRouteForRole(user.role)} replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route path="/register" element={<RegisterPage />} />
      <Route path="/register-org" element={<RegisterOrganisationPage />} />
      <Route path="/forgot-password" element={<ForgotPasswordPage />} />
      <Route path="/reset-password" element={<ResetPasswordPage />} />
      <Route path="/" element={<RootRedirect />} />

      {/* Student Dashboard Routes */}
      <Route
        element={
          <ProtectedRoute allowedRoles={["student"]}>
            <RoleLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/student" element={<StudentPortal />} />
      </Route>

      {/* Outlet Manager Dashboard Routes */}
      <Route
        element={
          <ProtectedRoute allowedRoles={["outlet_manager"]}>
            <RoleLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/manager" element={<OutletManagerDashboard />} />
        <Route path="/manager/scanner" element={<CounterScanner />} />
      </Route>

      {/* System Admin Dashboard Routes */}
      <Route
        element={
          <ProtectedRoute allowedRoles={["admin"]}>
            <RoleLayout />
          </ProtectedRoute>
        }
      >
        <Route path="/admin" element={<ManagerDashboard />} />
        <Route path="/admin/outlets" element={<AdminOutletsPage />} />
        <Route path="/admin/scanner" element={<CounterScanner />} />
      </Route>

      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
