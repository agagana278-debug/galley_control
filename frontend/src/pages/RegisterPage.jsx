import { useEffect, useState } from "react";
import { Building2, ChefHat, Lock, Mail, User, UserPlus } from "lucide-react";
import { Link, Navigate, useNavigate } from "react-router-dom";
import { fetchPublicOrganisations } from "../api/client";
import { getDefaultRouteForRole, useAuth } from "../context/AuthContext";

export default function RegisterPage() {
  const { user, authLoading, register } = useAuth();
  const navigate = useNavigate();

  const [organisations, setOrganisations] = useState([]);
  const [orgLoading, setOrgLoading] = useState(true);
  const [organisationId, setOrganisationId] = useState("");
  const [fullName, setFullName] = useState("");
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    let active = true;
    fetchPublicOrganisations()
      .then((res) => {
        if (!active) return;
        const list = res?.organisations || [];
        setOrganisations(list);
        if (list.length > 0) {
          setOrganisationId(String(list[0].id));
        }
      })
      .catch(() => {
        if (active) setError("Could not load active campus organisations.");
      })
      .finally(() => {
        if (active) setOrgLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  if (!authLoading && user) {
    return <Navigate to={getDefaultRouteForRole(user.role)} replace />;
  }

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (!organisationId) {
      setError("Please select your campus organisation.");
      return;
    }
    if (password !== confirmPassword) {
      setError("Passwords do not match.");
      return;
    }

    setSubmitting(true);
    try {
      const created = await register({
        full_name: fullName.trim(),
        username: username.trim(),
        email: email.trim(),
        password,
        confirm_password: confirmPassword,
        organisation_id: Number(organisationId),
      });
      navigate(getDefaultRouteForRole(created.role), { replace: true });
    } catch (err) {
      setError(err.message || "Registration failed. Please verify your details.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-navy-950 text-slate-100 flex items-center justify-center p-4 sm:p-6">
      <div className="max-w-md w-full rounded-2xl border border-slate-800 bg-navy-900/90 p-6 sm:p-8 space-y-5">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-xl bg-cyan-500/15 border border-cyan-400/40 flex items-center justify-center text-cyan-300">
            <ChefHat className="w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-white">
              Create Student Account
            </h1>
            <p className="text-xs text-slate-400">
              Public sign-up creates a Student profile; Manager & Admin roles require Administrator provisioning.
            </p>
          </div>
        </div>

        {error && (
          <div
            role="alert"
            className="rounded-xl border border-rose-500/50 bg-rose-950/40 px-4 py-3 text-xs text-rose-200"
          >
            {error}
          </div>
        )}

        <form onSubmit={handleSubmit} className="space-y-3.5 text-xs">
          <div className="space-y-1">
            <label className="block font-medium text-slate-300">
              Campus / College Organisation *
            </label>
            <div className="relative">
              <Building2 className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <select
                required
                disabled={orgLoading || organisations.length === 0}
                value={organisationId}
                onChange={(e) => setOrganisationId(e.target.value)}
                className="w-full rounded-xl bg-navy-950 border border-slate-700 pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
              >
                {organisations.length === 0 ? (
                  <option value="">
                    {orgLoading ? "Loading organisations..." : "No active organisations"}
                  </option>
                ) : (
                  organisations.map((org) => (
                    <option key={org.id} value={org.id}>
                      {org.name}
                      {org.campus_location ? ` (${org.campus_location})` : ""}
                    </option>
                  ))
                )}
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <label className="block font-medium text-slate-300">Full Name</label>
            <div className="relative">
              <User className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                required
                minLength={2}
                placeholder="e.g. Priya Nair"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="w-full rounded-xl bg-navy-950 border border-slate-700 pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="block font-medium text-slate-300">
              Username (letters, numbers, underscores)
            </label>
            <div className="relative">
              <User className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="text"
                required
                minLength={3}
                maxLength={32}
                placeholder="priya_nair"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                className="w-full rounded-xl bg-navy-950 border border-slate-700 pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="block font-medium text-slate-300">Email Address</label>
            <div className="relative">
              <Mail className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="email"
                required
                placeholder="priya@campus.edu"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                className="w-full rounded-xl bg-navy-950 border border-slate-700 pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="block font-medium text-slate-300">
              Password (min 8 chars, letters + digits)
            </label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                required
                minLength={8}
                placeholder="At least 8 characters"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                className="w-full rounded-xl bg-navy-950 border border-slate-700 pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
              />
            </div>
          </div>

          <div className="space-y-1">
            <label className="block font-medium text-slate-300">Confirm Password</label>
            <div className="relative">
              <Lock className="w-4 h-4 text-slate-500 absolute left-3 top-1/2 -translate-y-1/2" />
              <input
                type="password"
                required
                minLength={8}
                placeholder="Repeat password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                className="w-full rounded-xl bg-navy-950 border border-slate-700 pl-9 pr-3 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
              />
            </div>
          </div>

          <button
            type="submit"
            disabled={submitting}
            className="w-full py-2.5 rounded-xl bg-cyan-500 text-navy-950 font-bold text-sm hover:bg-cyan-400 disabled:opacity-50 inline-flex items-center justify-center gap-2"
          >
            <UserPlus className="w-4 h-4" />
            {submitting ? "Creating Account..." : "Register & Sign In"}
          </button>
        </form>

        <div className="text-center text-xs text-slate-400 pt-2 border-t border-slate-800 space-y-1.5">
          <div>
            Already registered?{" "}
            <Link to="/login" className="text-cyan-300 hover:text-cyan-200 font-semibold">
              Sign in here
            </Link>
          </div>
          <div>
            Onboarding a new campus canteen network?{" "}
            <Link to="/register-org" className="text-emerald-300 hover:text-emerald-200 font-semibold">
              Register Your Organisation
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
