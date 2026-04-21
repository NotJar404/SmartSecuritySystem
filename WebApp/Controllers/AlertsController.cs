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
        // INDEX (FILTERED VIEW)
        // =========================
        public async Task<IActionResult> Index(string filter = "all")
        {
            filter = (filter ?? "all").ToLower();

            IQueryable<Alert> query = _context.Alerts.AsNoTracking();

            query = filter switch
            {
                "new" => query.Where(a => a.Status == AlertStatus.New),
                "acknowledged" => query.Where(a => a.Status == AlertStatus.Acknowledged),
                "escalated" => query.Where(a => a.Status == AlertStatus.Escalated),
                "resolved" => query.Where(a => a.Status == AlertStatus.Resolved),
                _ => query
            };

            var data = await query
                .OrderByDescending(a => a.Severity)
                .ThenByDescending(a => a.Timestamp)
                .ToListAsync();

            ViewBag.Filter = filter;

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

            // keep consistent severity rule
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