import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertCircle, ArrowLeft, Building2, CheckCircle2, ShieldCheck } from "lucide-react";
import { registerOrganisation } from "../api/client";

function slugifyOrg(text) {
  return String(text || "")
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64);
}

export default function RegisterOrganisationPage() {
  const [form, setForm] = useState({
    org_name: "",
    org_slug: "",
    campus_location: "",
    contact_email: "",
    manager_full_name: "",
    manager_username: "",
    manager_email: "",
    password: "",
    confirm_password: "",
  });
  const [slugEdited, setSlugEdited] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState(null);

  const handleChange = (key, value) => {
    setForm((prev) => {
      const next = { ...prev, [key]: value };
      if (key === "org_name" && !slugEdited) {
        next.org_slug = slugifyOrg(value);
      }
      return next;
    });
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    if (form.password !== form.confirm_password) {
      setError("Passwords do not match.");
      return;
    }
    setSubmitting(true);
    try {
      const data = await registerOrganisation(form);
      setResult(data);
    } catch (err) {
      setError(err?.message || "Organisation onboarding failed.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-2xl bg-slate-900/90 border border-slate-800 rounded-2xl p-6 sm:p-8 shadow-2xl">
        <div className="flex items-center justify-between gap-4 mb-6">
          <div className="flex items-center gap-3">
            <div className="h-11 w-11 rounded-xl bg-cyan-500/15 border border-cyan-500/30 flex items-center justify-center text-cyan-300">
              <Building2 className="h-6 w-6" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-white">Onboard Campus Organisation</h1>
              <p className="text-xs text-slate-400">
                Register an independent college, university, or canteen network on Galley Control
              </p>
            </div>
          </div>
          <Link
            to="/login"
            className="inline-flex items-center gap-1.5 text-xs font-medium text-cyan-300 hover:text-cyan-200"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            Back to Sign In
          </Link>
        </div>

        {result ? (
          <div className="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-6 space-y-4">
            <div className="flex items-start gap-3">
              <CheckCircle2 className="h-6 w-6 text-emerald-400 shrink-0 mt-0.5" />
              <div>
                <h2 className="text-base font-semibold text-emerald-200">
                  Organisation Submitted for Platform Approval
                </h2>
                <p className="text-sm text-slate-300 mt-1">{result.message}</p>
              </div>
            </div>
            <div className="grid sm:grid-cols-2 gap-3 text-xs bg-slate-950/60 border border-slate-800 rounded-lg p-4">
              <div>
                <span className="text-slate-400 block">Organisation Name</span>
                <span className="font-semibold text-white">{result.organisation?.name}</span>
              </div>
              <div>
                <span className="text-slate-400 block">Tenant Slug</span>
                <span className="font-mono text-cyan-300">{result.organisation?.slug}</span>
              </div>
              <div>
                <span className="text-slate-400 block">Organisation Status</span>
                <span className="font-semibold text-amber-300">{result.organisation?.status}</span>
              </div>
              <div>
                <span className="text-slate-400 block">Primary Org Manager</span>
                <span className="font-semibold text-white">{result.manager?.email}</span>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3 pt-2">
              <Link
                to="/login"
                className="px-4 py-2 rounded-lg bg-cyan-500 hover:bg-cyan-400 text-slate-950 font-semibold text-sm transition"
              >
                Go to Login
              </Link>
              <button
                type="button"
                onClick={() => setResult(null)}
                className="px-4 py-2 rounded-lg border border-slate-700 hover:bg-slate-800 text-slate-200 text-sm transition"
              >
                Register Another Organisation
              </button>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-6">
            {error && (
              <div className="flex items-start gap-2.5 rounded-lg border border-rose-500/40 bg-rose-500/10 px-4 py-3 text-sm text-rose-200">
                <AlertCircle className="h-4 w-4 text-rose-400 shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            )}

            <div className="space-y-4">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-cyan-300">
                <Building2 className="h-3.5 w-3.5" />
                1. Organisation Details
              </div>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-300 mb-1">
                    College / Organisation Name *
                  </label>
                  <input
                    type="text"
                    required
                    minLength={3}
                    value={form.org_name}
                    onChange={(e) => handleChange("org_name", e.target.value)}
                    placeholder="e.g. Riverside Institute of Technology"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">
                    Organisation URL Slug *
                  </label>
                  <input
                    type="text"
                    required
                    minLength={3}
                    value={form.org_slug}
                    onChange={(e) => {
                      setSlugEdited(true);
                      handleChange("org_slug", slugifyOrg(e.target.value));
                    }}
                    placeholder="riverside-tech"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm font-mono text-cyan-200 focus:outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Campus / City</label>
                  <input
                    type="text"
                    value={form.campus_location}
                    onChange={(e) => handleChange("campus_location", e.target.value)}
                    placeholder="e.g. North Campus, Bengaluru"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">
                    Official Contact Email *
                  </label>
                  <input
                    type="email"
                    required
                    value={form.contact_email}
                    onChange={(e) => handleChange("contact_email", e.target.value)}
                    placeholder="canteen-admin@college.edu"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
              </div>
            </div>

            <div className="space-y-4 pt-2 border-t border-slate-800">
              <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-300">
                <ShieldCheck className="h-3.5 w-3.5" />
                2. Primary Organisation Manager Account
              </div>
              <div className="grid sm:grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Manager Full Name *</label>
                  <input
                    type="text"
                    required
                    minLength={2}
                    value={form.manager_full_name}
                    onChange={(e) => handleChange("manager_full_name", e.target.value)}
                    placeholder="Dr. Rohan Kapoor"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Manager Username *</label>
                  <input
                    type="text"
                    required
                    minLength={3}
                    value={form.manager_username}
                    onChange={(e) => handleChange("manager_username", e.target.value)}
                    placeholder="rohan_riverside"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
                <div className="sm:col-span-2">
                  <label className="block text-xs text-slate-300 mb-1">Manager Email *</label>
                  <input
                    type="email"
                    required
                    value={form.manager_email}
                    onChange={(e) => handleChange("manager_email", e.target.value)}
                    placeholder="rohan@college.edu"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Password *</label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={form.password}
                    onChange={(e) => handleChange("password", e.target.value)}
                    placeholder="Min 8 chars, upper/lower/digit/symbol"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
                <div>
                  <label className="block text-xs text-slate-300 mb-1">Confirm Password *</label>
                  <input
                    type="password"
                    required
                    minLength={8}
                    value={form.confirm_password}
                    onChange={(e) => handleChange("confirm_password", e.target.value)}
                    placeholder="Repeat password"
                    className="w-full bg-slate-950/70 border border-slate-700 rounded-lg px-3.5 py-2.5 text-sm text-white focus:outline-none focus:border-cyan-400"
                  />
                </div>
              </div>
            </div>

            <div className="rounded-lg bg-slate-950/60 border border-slate-800 p-3 text-xs text-slate-400">
              After submission, a Platform Administrator reviews and approves your organisation.
              Once active, your Organisation Manager can create multiple outlets, publish menus,
              and students from your campus can sign up with full tenant isolation.
            </div>

            <div className="flex items-center justify-between gap-4">
              <span className="text-xs text-slate-400">
                Joining an existing college as a student?{" "}
                <Link to="/register" className="text-cyan-300 hover:underline">
                  Student Sign Up
                </Link>
              </span>
              <button
                type="submit"
                disabled={submitting}
                className="px-5 py-2.5 rounded-lg bg-cyan-500 hover:bg-cyan-400 disabled:opacity-50 text-slate-950 font-semibold text-sm transition"
              >
                {submitting ? "Submitting..." : "Submit Organisation"}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  );
}
