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

            // BASE QUERY (DO NOT MATERIALIZE YET)
            var query = _context.Alerts.AsNoTracking().AsQueryable();

            // =========================
            // TOTAL COUNTS (FAST DB COUNT)
            // =========================
            ViewBag.TotalAll = await query.CountAsync();
            ViewBag.TotalNew = await query.CountAsync(a => a.Status == AlertStatus.New);
            ViewBag.TotalAcknowledged = await query.CountAsync(a => a.Status == AlertStatus.Acknowledged);
            ViewBag.TotalEscalated = await query.CountAsync(a => a.Status == AlertStatus.Escalated);
            ViewBag.TotalResolved = await query.CountAsync(a => a.Status == AlertStatus.Resolved);

            // =========================
            // FILTER BY STATUS
            // =========================
            query = filter switch
            {
                "new" => query.Where(a => a.Status == AlertStatus.New),
                "acknowledged" => query.Where(a => a.Status == AlertStatus.Acknowledged),
                "escalated" => query.Where(a => a.Status == AlertStatus.Escalated),
                "resolved" => query.Where(a => a.Status == AlertStatus.Resolved),
                _ => query
            };

            // =========================
            // SEARCH (Postgres-safe ILIKE)
            // =========================
            if (!string.IsNullOrWhiteSpace(search))
            {
                query = query.Where(a =>
                    EF.Functions.ILike(a.Type.ToString(), $"%{search}%") ||
                    EF.Functions.ILike(a.Status.ToString(), $"%{search}%") ||
                    EF.Functions.ILike(a.Severity.ToString(), $"%{search}%") ||
                    (a.Description != null && EF.Functions.ILike(a.Description, $"%{search}%")) ||
                    (a.RoomId.HasValue && a.RoomId.Value.ToString().Contains(search))
                );
            }

            // =========================
            // SORTING
            // =========================
            var finalData = await query
                .OrderByDescending(a => a.Severity)
                .ThenByDescending(a => a.Timestamp)
                .ToListAsync();

            ViewBag.Filter = filter;
            ViewBag.Search = search;

            return View(finalData);
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
            // =========================
            // LOAD ALERT WITH ROOM
            // =========================
            var alert = await _context.Alerts
                .Include(a => a.Room)
                .FirstOrDefaultAsync(a => a.AlertId == id);

            if (alert == null)
                return NotFound();

            // =========================
            // VALIDATION RULES
            // =========================
            if (alert.Status == AlertStatus.Resolved)
                return BadRequest("Resolved alerts cannot be escalated.");

            if (alert.Status == AlertStatus.Escalated)
                return RedirectToAction(nameof(Index));

            // =========================
            // UPDATE ALERT STATE
            // =========================
            alert.Status = AlertStatus.Escalated;
            alert.EscalatedAt = DateTime.UtcNow;
            alert.EscalatedBy = User.Identity?.Name ?? "Unknown";

            // Force CRITICAL severity when escalated
            alert.Severity = SeverityLevel.CRITICAL;

            // =========================
            // SAFE ROOM NAME RESOLUTION
            // =========================
            var roomName = alert.Room?.RoomName ?? $"Room {alert.RoomId}";

            // =========================
            // SYSTEM-WIDE NOTIFICATION
            // (VISIBLE TO ALL USERS)
            // =========================
            _context.Notifications.Add(new Notification
            {
                UserId = null, // system broadcast
                AlertId = alert.AlertId,
                Message = $"🚨 ALERT ESCALATED: Immediate attention required in {roomName}",
                IsRead = false,
                Timestamp = DateTime.UtcNow
            });

            // =========================
            // ADMIN NOTIFICATION ONLY
            // =========================
            var admin = await _context.Users
                .FirstOrDefaultAsync(u => u.Role == "Admin");

            if (admin != null)
            {
                _context.Notifications.Add(new Notification
                {
                    UserId = admin.Id,
                    AlertId = alert.AlertId,
                    Message = $"⚠️ Escalated alert requires administrative attention in {roomName}.",
                    IsRead = false,
                    Timestamp = DateTime.UtcNow
                });
            }

            // =========================
            // SAVE CHANGES
            // =========================
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