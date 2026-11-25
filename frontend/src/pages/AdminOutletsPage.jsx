import { useCallback, useEffect, useState } from "react";
import {
  Building2,
  Check,
  FileText,
  Plus,
  Save,
  Shield,
  Store,
  UserPlus,
  Users,
  X,
} from "lucide-react";
import { useOutletContext } from "react-router-dom";
import {
  createAdminOutlet,
  createAdminUser,
  fetchAdminOrganisations,
  fetchAdminOverview,
  updateAdminOutlet,
  updateAdminUser,
  updateOrganisationStatus,
} from "../api/client";

export default function AdminOutletsPage() {
  const { refreshNonce, triggerRefresh } = useOutletContext() || {};
  const [organisations, setOrganisations] = useState([]);
  const [selectedOrgId, setSelectedOrgId] = useState("");
  const [outlets, setOutlets] = useState([]);
  const [users, setUsers] = useState([]);
  const [auditLogs, setAuditLogs] = useState([]);
  const [drafts, setDrafts] = useState({});
  const [loading, setLoading] = useState(true);
  const [savingId, setSavingId] = useState(null);
  const [orgBusyId, setOrgBusyId] = useState(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  // Admin create outlet form
  const [newOutletOrgId, setNewOutletOrgId] = useState("");
  const [newOutletName, setNewOutletName] = useState("");
  const [newOutletLocation, setNewOutletLocation] = useState("");
  const [creatingOutlet, setCreatingOutlet] = useState(false);

  // Provision Outlet Manager form state
  const [mgrFullName, setMgrFullName] = useState("");
  const [mgrUsername, setMgrUsername] = useState("");
  const [mgrEmail, setMgrEmail] = useState("");
  const [mgrPassword, setMgrPassword] = useState("");
  const [mgrOutletId, setMgrOutletId] = useState(1);
  const [creatingMgr, setCreatingMgr] = useState(false);

  const loadOverview = useCallback(async () => {
    setError("");
    try {
      const orgFilter = selectedOrgId ? Number(selectedOrgId) : null;
      const [res, orgRes] = await Promise.all([
        fetchAdminOverview(orgFilter),
        fetchAdminOrganisations(),
      ]);
      const orgList = orgRes.organisations || res.organisations || [];
      setOrganisations(orgList);
      setOutlets(res.outlets || []);
      setUsers(res.users || []);
      setAuditLogs(res.audit_logs || []);
      const nextDrafts = {};
      (res.outlets || []).forEach((o) => {
        nextDrafts[o.id] = {
          status: o.status,
          active_staff: o.active_staff,
          avg_prep_minutes: o.avg_prep_minutes,
        };
      });
      setDrafts(nextDrafts);
      if (orgList.length && !newOutletOrgId) {
        setNewOutletOrgId(String(orgList[0].id));
      }
      if (res.outlets?.length && !mgrOutletId) {
        setMgrOutletId(res.outlets[0].id);
      }
    } catch (err) {
      setError(err.message || "Failed to load admin overview.");
    } finally {
      setLoading(false);
    }
  }, [selectedOrgId, newOutletOrgId, mgrOutletId]);

  useEffect(() => {
    loadOverview();
  }, [loadOverview, refreshNonce]);

  const handleOrgStatusChange = async (org, newStatus) => {
    setOrgBusyId(org.id);
    setError("");
    setNotice("");
    try {
      await updateOrganisationStatus(org.id, newStatus);
      setNotice(`Organisation "${org.name}" status updated to ${newStatus}.`);
      await loadOverview();
      if (triggerRefresh) triggerRefresh();
    } catch (err) {
      setError(err.message || "Could not update organisation status.");
    } finally {
      setOrgBusyId(null);
    }
  };

  const handleAdminCreateOutlet = async (e) => {
    e.preventDefault();
    if (!newOutletName.trim() || !newOutletLocation.trim()) return;
    setCreatingOutlet(true);
    setError("");
    setNotice("");
    try {
      const targetOrg = newOutletOrgId ? Number(newOutletOrgId) : organisations[0]?.id;
      const res = await createAdminOutlet({
        organisation_id: targetOrg,
        name: newOutletName.trim(),
        location: newOutletLocation.trim(),
        avg_prep_minutes: 6.0,
        active_staff: 3,
      });
      setNotice(`Provisioned outlet "${res.outlet.name}" under organisation.`);
      setNewOutletName("");
      setNewOutletLocation("");
      await loadOverview();
      if (triggerRefresh) triggerRefresh();
    } catch (err) {
      setError(err.message || "Failed to create outlet.");
    } finally {
      setCreatingOutlet(false);
    }
  };

  const handleSaveOutlet = async (outletId, outletName) => {
    const draft = drafts[outletId];
    if (!draft) return;
    setSavingId(outletId);
    setError("");
    setNotice("");
    try {
      await updateAdminOutlet(outletId, {
        status: draft.status,
        active_staff: Number(draft.active_staff),
        avg_prep_minutes: Number(draft.avg_prep_minutes),
      });
      setNotice(`Saved configuration for ${outletName}.`);
      await loadOverview();
      if (triggerRefresh) triggerRefresh();
    } catch (err) {
      setError(err.message || "Failed to update outlet configuration.");
    } finally {
      setSavingId(null);
    }
  };

  const handleCreateManager = async (e) => {
    e.preventDefault();
    setError("");
    setNotice("");
    setCreatingMgr(true);
    try {
      const targetOutlet = outlets.find((o) => o.id === Number(mgrOutletId));
      await createAdminUser({
        full_name: mgrFullName.trim(),
        username: mgrUsername.trim(),
        email: mgrEmail.trim(),
        password: mgrPassword,
        role: "outlet_manager",
        organisation_id: targetOutlet?.organisation_id ?? null,
        outlet_id: Number(mgrOutletId),
      });
      setNotice(`Provisioned Outlet Manager account '${mgrUsername.trim()}'.`);
      setMgrFullName("");
      setMgrUsername("");
      setMgrEmail("");
      setMgrPassword("");
      await loadOverview();
    } catch (err) {
      setError(err.message || "Could not provision manager account.");
    } finally {
      setCreatingMgr(false);
    }
  };

  const handleToggleUserActive = async (targetUser) => {
    setError("");
    setNotice("");
    try {
      await updateAdminUser(targetUser.id, {
        is_active: !targetUser.is_active,
      });
      setNotice(
        `${targetUser.username} marked ${!targetUser.is_active ? "ACTIVE" : "INACTIVE"}.`
      );
      await loadOverview();
    } catch (err) {
      setError(err.message || "Failed to update user status.");
    }
  };

  if (loading && !outlets.length) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[400px] rounded-3xl border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900/60 p-12 text-center shadow-sm">
        <div className="w-10 h-10 border-4 border-indigo-600 border-t-transparent rounded-full animate-spin mb-4" />
        <div className="text-base font-semibold text-slate-800 dark:text-slate-200">
          Loading Directory & System State
        </div>
        <div className="text-xs text-slate-500 mt-1">
          Fetching multi-tenant organisations, kitchen outlets, and audit logs...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-8">
      {/* Page Title & Organisation Filter */}
      <div className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-extrabold text-slate-900 dark:text-white tracking-tight flex items-center gap-2">
            <Store className="w-5 h-5 text-indigo-600" />
            <span>Campus Organisations & Outlet Directory</span>
          </h2>
          <p className="text-xs text-slate-500 mt-1">
            Approve registered colleges, provision manager credentials, and configure service level agreements.
          </p>
        </div>

        <div className="flex items-center gap-2 text-xs">
          <span className="text-slate-500 font-semibold">Filter Org:</span>
          <select
            aria-label="Filter overview by organisation"
            value={selectedOrgId}
            onChange={(e) => setSelectedOrgId(e.target.value)}
            className="rounded-2xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3.5 py-2 text-slate-800 dark:text-slate-200 font-semibold focus:outline-none"
          >
            <option value="">All Organisations ({organisations.length})</option>
            {organisations.map((org) => (
              <option key={org.id} value={org.id}>
                {org.name} ({org.status})
              </option>
            ))}
          </select>
        </div>
      </div>

      {error && (
        <div className="rounded-2xl border border-rose-300 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 px-5 py-4 text-xs text-rose-800 dark:text-rose-200">
          {error}
        </div>
      )}

      {notice && (
        <div className="rounded-2xl border border-emerald-300 dark:border-emerald-800 bg-emerald-50 dark:bg-emerald-950/40 px-5 py-4 text-xs text-emerald-800 dark:text-emerald-200">
          {notice}
        </div>
      )}

      {/* Registered Campus Organisations Table & Quick Provisioning */}
      <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-5">
        <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-100 dark:border-slate-800">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
            <Building2 className="w-4 h-4 text-emerald-600" />
            <span>Registered Campus Organisations ({organisations.length})</span>
          </h3>
          <span className="text-[11px] text-slate-400">
            Pending tenants are completely isolated until approved by Platform Admin.
          </span>
        </div>

        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs">
            <thead>
              <tr className="border-b border-slate-100 dark:border-slate-800 text-slate-400 uppercase text-[10px] tracking-wider">
                <th className="py-3 px-3">Organisation</th>
                <th className="py-3 px-3">Domain / Campus</th>
                <th className="py-3 px-3">Counters / Users</th>
                <th className="py-3 px-3">Status</th>
                <th className="py-3 px-3 text-right">Platform Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {organisations.map((org) => (
                <tr key={org.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition">
                  <td className="py-3 px-3">
                    <div className="font-bold text-slate-900 dark:text-white">{org.name}</div>
                    <div className="text-[11px] text-slate-500">{org.contact_email}</div>
                  </td>
                  <td className="py-3 px-3">
                    <div className="font-mono text-indigo-600 dark:text-indigo-400 font-semibold">{org.slug}</div>
                    <div className="text-[11px] text-slate-500">{org.campus_location || "—"}</div>
                  </td>
                  <td className="py-3 px-3 text-slate-600 dark:text-slate-300 font-medium">
                    {org.outlet_count} counters • {org.user_count} accounts
                  </td>
                  <td className="py-3 px-3">
                    <span
                      className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                        org.status === "ACTIVE"
                          ? "bg-emerald-100 text-emerald-800"
                          : org.status === "PENDING_APPROVAL"
                            ? "bg-amber-100 text-amber-800"
                            : "bg-rose-100 text-rose-800"
                      }`}
                    >
                      {org.status}
                    </span>
                  </td>
                  <td className="py-3 px-3 text-right space-x-2">
                    {org.status !== "ACTIVE" && (
                      <button
                        type="button"
                        disabled={orgBusyId === org.id}
                        onClick={() => handleOrgStatusChange(org, "ACTIVE")}
                        className="px-3 py-1 rounded-xl bg-emerald-600 text-white font-bold hover:bg-emerald-700 shadow-xs"
                      >
                        Approve
                      </button>
                    )}
                    {org.status === "ACTIVE" && (
                      <button
                        type="button"
                        disabled={orgBusyId === org.id}
                        onClick={() => handleOrgStatusChange(org, "SUSPENDED")}
                        className="px-3 py-1 rounded-xl bg-amber-500 text-white font-bold hover:bg-amber-600 shadow-xs"
                      >
                        Suspend
                      </button>
                    )}
                    {org.status === "PENDING_APPROVAL" && (
                      <button
                        type="button"
                        disabled={orgBusyId === org.id}
                        onClick={() => handleOrgStatusChange(org, "REJECTED")}
                        className="px-3 py-1 rounded-xl bg-rose-600 text-white font-bold hover:bg-rose-700 shadow-xs"
                      >
                        Reject
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>

        {/* Quick Admin Add Counter to any Active Org */}
        <form onSubmit={handleAdminCreateOutlet} className="pt-4 border-t border-slate-100 dark:border-slate-800 grid sm:grid-cols-4 gap-3 text-xs">
          <select
            value={newOutletOrgId}
            onChange={(e) => setNewOutletOrgId(e.target.value)}
            className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3.5 py-2.5 text-slate-800 dark:text-slate-200"
          >
            {organisations.map((org) => (
              <option key={org.id} value={org.id}>
                Org: {org.name}
              </option>
            ))}
          </select>
          <input
            type="text"
            required
            minLength={2}
            placeholder="New Counter Name"
            value={newOutletName}
            onChange={(e) => setNewOutletName(e.target.value)}
            className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3.5 py-2.5 text-slate-800 dark:text-slate-200"
          />
          <input
            type="text"
            required
            minLength={2}
            placeholder="Campus Location"
            value={newOutletLocation}
            onChange={(e) => setNewOutletLocation(e.target.value)}
            className="rounded-2xl border border-slate-200 dark:border-slate-700 bg-slate-50 dark:bg-slate-950 px-3.5 py-2.5 text-slate-800 dark:text-slate-200"
          />
          <button
            type="submit"
            disabled={creatingOutlet}
            className="rounded-2xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold px-4 py-2.5 shadow-sm inline-flex items-center justify-center gap-1.5 transition"
          >
            <Plus className="w-4 h-4" />
            <span>{creatingOutlet ? "Provisioning..." : "Add Counter"}</span>
          </button>
        </form>
      </section>

      {/* Outlets Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
        {outlets.map((o) => {
          const d = drafts[o.id] || {
            status: o.status,
            active_staff: o.active_staff,
            avg_prep_minutes: o.avg_prep_minutes,
          };
          return (
            <div
              key={o.id}
              className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4 text-xs"
            >
              <div className="flex items-start justify-between gap-2">
                <div>
                  <h3 className="text-base font-bold text-slate-900 dark:text-white">{o.name}</h3>
                  <p className="text-slate-500 mt-0.5">{o.location}</p>
                </div>
                <span
                  className={`px-2.5 py-0.5 rounded-full text-[10px] font-bold uppercase tracking-wider ${
                    o.status === "OPEN"
                      ? "bg-emerald-100 text-emerald-800"
                      : o.status === "BUSY"
                        ? "bg-amber-100 text-amber-800"
                        : "bg-rose-100 text-rose-800"
                  }`}
                >
                  {o.status}
                </span>
              </div>

              <div className="grid grid-cols-3 gap-2 rounded-2xl bg-slate-50 dark:bg-slate-950 p-3 text-center border border-slate-100 dark:border-slate-800">
                <div>
                  <div className="text-sm font-black text-slate-900 dark:text-white">{o.open_orders}</div>
                  <div className="text-[10px] text-slate-400">Queue</div>
                </div>
                <div>
                  <div className="text-sm font-black text-slate-900 dark:text-white">{o.low_stock_count}</div>
                  <div className="text-[10px] text-slate-400">Low Stock</div>
                </div>
                <div>
                  <div className="text-sm font-black text-indigo-600 dark:text-indigo-400">
                    ₹{Number(o.live_revenue || 0).toFixed(0)}
                  </div>
                  <div className="text-[10px] text-slate-400">Sales</div>
                </div>
              </div>

              <div className="space-y-3">
                <div>
                  <label className="block text-[10px] uppercase font-bold text-slate-400 mb-1">
                    Operational Status
                  </label>
                  <select
                    value={d.status}
                    onChange={(e) =>
                      setDrafts((prev) => ({
                        ...prev,
                        [o.id]: { ...d, status: e.target.value },
                      }))
                    }
                    className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
                  >
                    <option value="OPEN">OPEN</option>
                    <option value="BUSY">BUSY</option>
                    <option value="CLOSED">CLOSED</option>
                  </select>
                </div>

                <div className="grid grid-cols-2 gap-2.5">
                  <div>
                    <label className="block text-[10px] uppercase font-bold text-slate-400 mb-1">
                      Staff Count
                    </label>
                    <input
                      type="number"
                      min={1}
                      max={50}
                      value={d.active_staff}
                      onChange={(e) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [o.id]: { ...d, active_staff: e.target.value },
                        }))
                      }
                      className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
                    />
                  </div>
                  <div>
                    <label className="block text-[10px] uppercase font-bold text-slate-400 mb-1">
                      Avg Prep SLA (min)
                    </label>
                    <input
                      type="number"
                      step="0.5"
                      min={1}
                      max={60}
                      value={d.avg_prep_minutes}
                      onChange={(e) =>
                        setDrafts((prev) => ({
                          ...prev,
                          [o.id]: { ...d, avg_prep_minutes: e.target.value },
                        }))
                      }
                      className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
                    />
                  </div>
                </div>

                <button
                  type="button"
                  disabled={savingId === o.id}
                  onClick={() => handleSaveOutlet(o.id, o.name)}
                  className="w-full py-2.5 rounded-2xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold transition shadow-sm inline-flex items-center justify-center gap-2"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>{savingId === o.id ? "Saving..." : "Save Configuration"}</span>
                </button>
              </div>
            </div>
          );
        })}
      </div>

      {/* Provision Manager & User Accounts Directory */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-8 items-start">
        <section className="lg:col-span-4 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4 text-xs">
          <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2 pb-3 border-b border-slate-100 dark:border-slate-800">
            <UserPlus className="w-4 h-4 text-indigo-600" />
            <span>Provision Outlet Supervisor</span>
          </h3>

          <form onSubmit={handleCreateManager} className="space-y-3">
            <div>
              <label className="block text-[10px] font-bold uppercase text-slate-400 mb-1">Full Name</label>
              <input
                type="text"
                required
                placeholder="Rohan Sharma"
                value={mgrFullName}
                onChange={(e) => setMgrFullName(e.target.value)}
                className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
              />
            </div>
            <div>
              <label className="block text-[10px] font-bold uppercase text-slate-400 mb-1">Username</label>
              <input
                type="text"
                required
                placeholder="rohan_mgr"
                value={mgrUsername}
                onChange={(e) => setMgrUsername(e.target.value)}
                className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
              />
            </div>
            <div>
              <label className="block text-[10px] font-bold uppercase text-slate-400 mb-1">Email</label>
              <input
                type="email"
                required
                placeholder="manager@campus.edu"
                value={mgrEmail}
                onChange={(e) => setMgrEmail(e.target.value)}
                className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
              />
            </div>
            <div>
              <label className="block text-[10px] font-bold uppercase text-slate-400 mb-1">Temporary Password</label>
              <input
                type="password"
                required
                minLength={8}
                placeholder="Min 8 chars"
                value={mgrPassword}
                onChange={(e) => setMgrPassword(e.target.value)}
                className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
              />
            </div>
            <div>
              <label className="block text-[10px] font-bold uppercase text-slate-400 mb-1">Assign Counter</label>
              <select
                value={mgrOutletId}
                onChange={(e) => setMgrOutletId(e.target.value)}
                className="w-full rounded-xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-700 px-3 py-2 text-slate-800 dark:text-slate-200"
              >
                {outlets.map((o) => (
                  <option key={o.id} value={o.id}>
                    {o.name}
                  </option>
                ))}
              </select>
            </div>
            <button
              type="submit"
              disabled={creatingMgr}
              className="w-full py-2.5 rounded-2xl bg-indigo-600 hover:bg-indigo-700 text-white font-bold transition shadow-sm"
            >
              {creatingMgr ? "Creating..." : "Create Supervisor Account"}
            </button>
          </form>
        </section>

        {/* User Accounts Directory */}
        <section className="lg:col-span-8 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4">
          <div className="flex items-center justify-between pb-3 border-b border-slate-100 dark:border-slate-800">
            <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <Users className="w-4 h-4 text-indigo-600" />
              <span>User Directory & Role Permissions ({users.length})</span>
            </h3>
            <span className="text-[11px] text-emerald-600 font-bold flex items-center gap-1">
              <Shield className="w-3.5 h-3.5" />
              PBKDF2/Bcrypt RBAC
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left text-xs">
              <thead>
                <tr className="border-b border-slate-100 dark:border-slate-800 text-slate-400 uppercase text-[10px] tracking-wider">
                  <th className="py-2.5 px-3">Name</th>
                  <th className="py-2.5 px-3">Username</th>
                  <th className="py-2.5 px-3">Role</th>
                  <th className="py-2.5 px-3">Counter</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3 text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                {users.map((u) => (
                  <tr key={u.id} className="hover:bg-slate-50 dark:hover:bg-slate-800/40 transition">
                    <td className="py-2.5 px-3 font-bold text-slate-900 dark:text-white">{u.full_name}</td>
                    <td className="py-2.5 px-3 text-slate-500">{u.username}</td>
                    <td className="py-2.5 px-3 font-semibold uppercase text-indigo-600 dark:text-indigo-400 text-[10px]">
                      {u.role}
                    </td>
                    <td className="py-2.5 px-3 text-slate-500">{u.outlet_name || "Campus-Wide"}</td>
                    <td className="py-2.5 px-3">
                      <span
                        className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                          u.is_active ? "bg-emerald-100 text-emerald-800" : "bg-rose-100 text-rose-800"
                        }`}
                      >
                        {u.is_active ? "ACTIVE" : "INACTIVE"}
                      </span>
                    </td>
                    <td className="py-2.5 px-3 text-right">
                      {u.role !== "admin" && (
                        <button
                          type="button"
                          onClick={() => handleToggleUserActive(u)}
                          className="px-2.5 py-1 rounded-xl bg-slate-100 dark:bg-slate-800 hover:bg-slate-200 text-slate-700 dark:text-slate-300 font-semibold text-[11px]"
                        >
                          {u.is_active ? "Deactivate" : "Activate"}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      </div>

      {/* System Audit Trail Stream */}
      <section className="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-3xl p-6 shadow-sm space-y-4">
        <h3 className="text-sm font-bold text-slate-900 dark:text-white flex items-center gap-2 pb-3 border-b border-slate-100 dark:border-slate-800">
          <FileText className="w-4 h-4 text-indigo-600" />
          <span>System Audit Log ({auditLogs.length})</span>
        </h3>

        <div className="space-y-2 max-h-60 overflow-y-auto pr-1 text-xs">
          {auditLogs.map((log) => (
            <div
              key={log.id}
              className="rounded-2xl bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 px-4 py-2.5 flex flex-wrap items-center justify-between gap-2"
            >
              <div>
                <span className="font-bold text-indigo-600 dark:text-indigo-400">{log.action}</span>{" "}
                <span className="text-slate-400">({log.resource_type}:{log.resource_id || "-"})</span>{" "}
                <span className="text-slate-600 dark:text-slate-300">{log.details_json || ""}</span>
              </div>
              <span className="text-[11px] text-slate-400">
                role={log.actor_role || "anon"} • {log.created_at}
              </span>
            </div>
          ))}
        </div>
      </section>
    </div>
  );
}
