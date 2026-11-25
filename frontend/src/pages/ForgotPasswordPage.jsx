import { useEffect, useState } from "react";
import { AlertTriangle, ArrowLeft, CheckCircle2, ChefHat, Mail, Send } from "lucide-react";
import { Link } from "react-router-dom";
import { forgotPassword, getEmailStatus } from "../api/client";

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState("");
  const [emailStatus, setEmailStatus] = useState(null);

  useEffect(() => {
    getEmailStatus()
      .then((data) => setEmailStatus(data))
      .catch(() => setEmailStatus({ configured: false, mode: "unconfigured" }));
  }, []);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError("");
    setSubmitting(true);
    try {
      const res = await forgotPassword(email.trim());
      if (res?.status === "unconfigured") {
        setError(res.message || "SMTP email delivery is not configured on the server. Please set SMTP credentials in backend/.env.");
        return;
      }
      if (res?.status === "delivery_failed") {
        setError(res.message || "Failed to dispatch password reset email via SMTP. Please check server logs.");
        return;
      }
      setSubmitted(true);
    } catch (err) {
      setError(err.message || "Unable to process password reset request. Please try again later.");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="min-h-screen bg-slate-50 dark:bg-[#0b0f19] text-slate-900 dark:text-slate-100 flex items-center justify-center p-4 sm:p-6 transition-colors duration-200">
      <div className="max-w-md w-full bg-white dark:bg-slate-900 rounded-3xl border border-slate-200 dark:border-slate-800 p-8 shadow-sm space-y-6">
        {/* Brand Header */}
        <div className="space-y-3">
          <div className="flex items-center gap-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-700 to-indigo-500 flex items-center justify-center text-white shadow-md shadow-indigo-500/20">
              <ChefHat className="w-5 h-5" />
            </div>
            <div>
              <div className="text-base font-extrabold tracking-tight text-slate-900 dark:text-white leading-none">
                GALLEY<span className="text-indigo-600 dark:text-indigo-400"> CONTROL</span>
              </div>
              <div className="text-[11px] font-medium text-slate-500 dark:text-slate-400 mt-0.5">
                Password Recovery
              </div>
            </div>
          </div>

          <div>
            <h1 className="text-xl font-bold text-slate-900 dark:text-white">Reset Your Password</h1>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-1">
              Enter your registered email address to receive a secure, single-use reset link.
            </p>
          </div>
        </div>

        {/* Configuration Notice if SMTP is unconfigured */}
        {emailStatus && !emailStatus.configured && (
          <div
            role="status"
            className="rounded-2xl border border-amber-300 dark:border-amber-800 bg-amber-50 dark:bg-amber-950/40 p-4 text-xs text-amber-900 dark:text-amber-200 shadow-sm space-y-1.5"
          >
            <div className="flex items-center gap-2 font-bold text-amber-800 dark:text-amber-300">
              <AlertTriangle className="w-4 h-4 shrink-0 text-amber-600 dark:text-amber-400" />
              <span>SMTP email delivery is not configured (noop).</span>
            </div>
            <p className="text-[11px] text-amber-700 dark:text-amber-300 leading-relaxed">
              Outgoing mail delivery is currently disabled. To dispatch real password-reset emails, configure <code>SMTP_HOST</code>, <code>SMTP_PORT</code>, <code>SMTP_USER</code>, and <code>SMTP_PASSWORD</code> in <code>backend/.env</code>.
            </p>
          </div>
        )}

        {error && (
          <div
            role="alert"
            className="rounded-2xl border border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 px-4 py-3 text-xs text-rose-800 dark:text-rose-200 shadow-sm"
          >
            {error}
          </div>
        )}

        {submitted ? (
          <div className="space-y-4">
            <div className="rounded-2xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 p-4 text-xs text-emerald-900 dark:text-emerald-200 shadow-sm space-y-2">
              <div className="flex items-center gap-2 font-bold text-emerald-800 dark:text-emerald-300">
                <CheckCircle2 className="w-4 h-4 shrink-0 text-emerald-600 dark:text-emerald-400" />
                <span>Reset Instructions Dispatched</span>
              </div>
              <p className="text-[11px] text-emerald-700 dark:text-emerald-300 leading-relaxed">
                If an active account exists for <strong>{email}</strong>, a single-use password reset link has been dispatched. Please check your inbox and spam folder within the next few minutes.
              </p>
            </div>

            <div className="pt-2 text-center">
              <Link
                to="/login"
                className="inline-flex items-center gap-2 px-5 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md shadow-indigo-600/20 transition"
              >
                <ArrowLeft className="w-3.5 h-3.5" />
                <span>Return to Sign In</span>
              </Link>
            </div>
          </div>
        ) : (
          <form onSubmit={handleSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <label
                htmlFor="reset-email"
                className="block text-xs font-semibold text-slate-700 dark:text-slate-300"
              >
                Registered Email Address
              </label>
              <div className="relative">
                <Mail className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
                <input
                  id="reset-email"
                  type="email"
                  required
                  autoComplete="email"
                  placeholder="you@campus.edu"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  className="w-full rounded-2xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 pl-10 pr-4 py-3 text-xs text-slate-900 dark:text-white placeholder:text-slate-400 focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>
            </div>

            <button
              type="submit"
              disabled={submitting}
              className="w-full py-3 rounded-2xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold text-xs shadow-md shadow-indigo-600/30 disabled:opacity-50 flex items-center justify-center gap-2 transition"
            >
              <Send className="w-4 h-4" />
              <span>{submitting ? "Sending Request..." : "Send Password Reset Link"}</span>
            </button>
          </form>
        )}

        <div className="flex items-center justify-between text-xs pt-4 border-t border-slate-100 dark:border-slate-800">
          <Link
            to="/login"
            className="inline-flex items-center gap-1.5 text-slate-600 dark:text-slate-400 hover:text-indigo-600 dark:hover:text-indigo-400 font-medium transition"
          >
            <ArrowLeft className="w-3.5 h-3.5" />
            <span>Back to Sign In</span>
          </Link>
          <Link
            to="/reset-password"
            className="text-indigo-600 dark:text-indigo-400 hover:underline font-medium"
          >
            Have a reset token?
          </Link>
        </div>
      </div>
    </div>
  );
}
