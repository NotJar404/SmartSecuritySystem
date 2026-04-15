using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.EntityFrameworkCore;
using WebApp.Data;
using WebApp.Models;
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
        // VIEW ALERTS WITH FILTER
        // =========================
        public async Task<IActionResult> Index(string filter = "all")
        {
            filter = filter?.ToLower() ?? "all";

            IQueryable<WebApp.Models.Alert> query = _context.Alerts;

            query = filter switch
            {
                "new" => query.Where(a => a.Status == WebApp.Models.AlertStatus.New),
                "acknowledged" => query.Where(a => a.Status == WebApp.Models.AlertStatus.Acknowledged),
                "resolved" => query.Where(a => a.Status == WebApp.Models.AlertStatus.Resolved),
                _ => query
            };

            ViewBag.Filter = filter;

            var data = await query
                .OrderByDescending(a => a.Timestamp)
                .AsNoTracking()
                .ToListAsync();

            return View(data);
        }

        // =========================
        // ACKNOWLEDGE ALERT
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Acknowledge(int id)
        {
            var alert = await _context.Alerts
                .FirstOrDefaultAsync(a => a.AlertId == id);

            if (alert == null)
                return NotFound();

            if (alert.Status == WebApp.Models.AlertStatus.New)
            {
                alert.Status = WebApp.Models.AlertStatus.Acknowledged;
                await _context.SaveChangesAsync();
            }

            return RedirectToAction(nameof(Index));
        }

        // =========================
        // RESOLVE ALERT
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Resolve(int id)
        {
            var alert = await _context.Alerts
                .FirstOrDefaultAsync(a => a.AlertId == id);

            if (alert == null)
                return NotFound();

            if (alert.Status != WebApp.Models.AlertStatus.Resolved)
            {
                alert.Status = WebApp.Models.AlertStatus.Resolved;
                await _context.SaveChangesAsync();
            }

            return RedirectToAction(nameof(Index));
        }

        // =========================
        // ESCALATE ALERT
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public async Task<IActionResult> Escalate(int id)
        {
            var alert = await _context.Alerts
                .FirstOrDefaultAsync(a => a.AlertId == id);

            if (alert == null)
                return NotFound();

            // escalate severity
            alert.Severity = WebApp.Models.SeverityLevel.CRITICAL;

            // only reset status if not resolved
            if (alert.Status != WebApp.Models.AlertStatus.Resolved)
            {
                alert.Status = WebApp.Models.AlertStatus.New;
            }

            await _context.SaveChangesAsync();

            return RedirectToAction(nameof(Index));
        }
    }
}