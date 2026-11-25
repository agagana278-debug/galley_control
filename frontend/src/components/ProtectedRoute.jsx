import { LockKeyhole, ShieldAlert } from "lucide-react";
import { Link, Navigate, useLocation } from "react-router-dom";
import { getDefaultRouteForRole, getRoleLabel, useAuth } from "../context/AuthContext";

export default function ProtectedRoute({ allowedRoles, children }) {
  const { user, authLoading } = useAuth();
  const location = useLocation();

  if (authLoading) {
    return (
      <div className="min-h-screen bg-navy-950 text-slate-100 flex items-center justify-center p-6">
        <div className="rounded-2xl border border-slate-800 bg-navy-900/80 px-6 py-5 text-sm text-slate-300">
          Restoring authenticated session...
        </div>
      </div>
    );
  }

  if (!user) {
    return (
      <Navigate
        to="/login"
        state={{ from: `${location.pathname}${location.search}` }}
        replace
      />
    );
  }

  if (allowedRoles && !allowedRoles.includes(user.role)) {
    const fallbackRoute = getDefaultRouteForRole(user.role);
    return (
      <div className="min-h-screen bg-navy-950 text-slate-100 flex items-center justify-center p-6">
        <div className="max-w-md w-full rounded-2xl border border-rose-500/40 bg-navy-900/90 p-6 space-y-4 text-center">
          <div className="mx-auto w-12 h-12 rounded-2xl bg-rose-500/15 border border-rose-500/40 flex items-center justify-center text-rose-300">
            <ShieldAlert className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <div className="text-xs font-bold uppercase tracking-wider text-rose-300">
              403 • Unauthorised Route
            </div>
            <h1 className="text-lg font-bold text-white">
              Access Restricted for {getRoleLabel(user.role)}
            </h1>
            <p className="text-xs text-slate-400">
              Signed in as <strong className="text-slate-200">{user.email}</strong>. You do not have permission to open{" "}
              <code className="text-cyan-300">{location.pathname}</code>.
            </p>
          </div>
          <Link
            to={fallbackRoute}
            className="inline-flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-cyan-500 text-navy-950 text-xs font-bold hover:bg-cyan-400"
          >
            <LockKeyhole className="w-4 h-4" />
            Return to My {getRoleLabel(user.role)} Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return children;
}
