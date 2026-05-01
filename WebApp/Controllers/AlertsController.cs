using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
using System;
using System.Linq;
using System.Threading.Tasks;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class AlertsController : Controller
    {
        private readonly AppDbContext _context;

        public AlertsController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // INDEX (FILTER + SEARCH)
        // =========================
        public async Task<IActionResult> Index(string filter = "all", string search = "")
        {
            filter = (filter ?? "all").Trim().ToLower();
            search = (search ?? "").Trim();

            IQueryable<Alert> query = _context.Alerts.AsNoTracking();

            // =========================
            // FILTER BY STATUS
            // =========================
            switch (filter)
            {
                case "new":
                    query = query.Where(a => a.Status == AlertStatus.New);
                    break;

                case "acknowledged":
                    query = query.Where(a => a.Status == AlertStatus.Acknowledged);
                    break;

                case "escalated":
                    query = query.Where(a => a.Status == AlertStatus.Escalated);
                    break;

                case "resolved":
                    query = query.Where(a => a.Status == AlertStatus.Resolved);
                    break;

                default:
                    break;
            }

            // =========================
            // SEARCH (SAFE + CASE INSENSITIVE)
            // =========================
            // =========================
            // TOTAL COUNTS (BEFORE FILTERING — for filter button labels)
            // =========================
            var allAlerts = _context.Alerts.AsNoTracking();
            ViewBag.TotalAll = await allAlerts.CountAsync();
            ViewBag.TotalNew = await allAlerts.CountAsync(a => a.Status == AlertStatus.New);
            ViewBag.TotalAcknowledged = await allAlerts.CountAsync(a => a.Status == AlertStatus.Acknowledged);
            ViewBag.TotalEscalated = await allAlerts.CountAsync(a => a.Status == AlertStatus.Escalated);
            ViewBag.TotalResolved = await allAlerts.CountAsync(a => a.Status == AlertStatus.Resolved);

            if (!string.IsNullOrWhiteSpace(search))
            {
                var s = search.ToLower();

                query = query.Where(a =>
                    a.Type.ToString().ToLower().Contains(s) ||
                    a.Status.ToString().ToLower().Contains(s) ||
                    a.Severity.ToString().ToLower().Contains(s) ||
                    (a.Description != null && a.Description.ToLower().Contains(s)) ||
                    (a.RoomId.HasValue && a.RoomId.Value.ToString().Contains(s))
                );
            }

            // =========================
            // SORTING
            // =========================
            var data = await query
                .OrderByDescending(a => a.Severity)
                .ThenByDescending(a => a.Timestamp)
                .ToListAsync();

            // Pass back to view
            ViewBag.Filter = filter;
            ViewBag.Search = search;

            return View(data);
        }

        // =========================
        // ACKNOWLEDGE ALERT
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Acknowledge(int id)
        {
            var alert = await _context.Alerts.FindAsync(id);
            if (alert == null) return NotFound();

            if (alert.Status != AlertStatus.New)
                return BadRequest("Only NEW alerts can be acknowledged.");

            alert.Status = AlertStatus.Acknowledged;
            alert.AcknowledgedAt = DateTime.UtcNow;
            alert.AcknowledgedBy = User.Identity?.Name ?? "Unknown";

            await _context.SaveChangesAsync();

            return RedirectToAction(nameof(Index));
        }

        // =========================
        // ESCALATE ALERT
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Escalate(int id)
        {
            var alert = await _context.Alerts.FindAsync(id);
            if (alert == null) return NotFound();

            if (alert.Status == AlertStatus.Resolved)
                return BadRequest("Resolved alerts cannot be escalated.");

            if (alert.Status == AlertStatus.Escalated)
                return RedirectToAction(nameof(Index));

            alert.Status = AlertStatus.Escalated;
            alert.EscalatedAt = DateTime.UtcNow;
            alert.EscalatedBy = User.Identity?.Name ?? "Unknown";

            // Force critical severity when escalated
            alert.Severity = SeverityLevel.CRITICAL;

            await _context.SaveChangesAsync();

            return RedirectToAction(nameof(Index));
        }

        // =========================
        // RESOLVE ALERT
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Resolve(int id)
        {
            var alert = await _context.Alerts.FindAsync(id);
            if (alert == null) return NotFound();

            if (alert.Status == AlertStatus.New)
                return BadRequest("Must acknowledge before resolving.");

            if (alert.Status == AlertStatus.Resolved)
                return RedirectToAction(nameof(Index));

            alert.Status = AlertStatus.Resolved;
            alert.ResolvedAt = DateTime.UtcNow;
            alert.ResolvedBy = User.Identity?.Name ?? "Unknown";

            await _context.SaveChangesAsync();

            return RedirectToAction(nameof(Index));
        }
    }
}