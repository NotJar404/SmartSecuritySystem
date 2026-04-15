using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Models;
using WebApp.Data;
using System.Linq;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class LogsController : Controller
    {
        private readonly AppDbContext _context;

        public LogsController(AppDbContext context)
        {
            _context = context;
        }

        public IActionResult Index()
        {
            var logs = new List<LogEntry>();

            // 🔐 LOGIN LOGS (from Users table)
            logs.AddRange(_context.Users
                .Where(u => u.LastLogin != null)
                .Select(u => new LogEntry
                {
                    Id = u.Id,
                    Action = "User Login",
                    User = u.Username,
                    Details = "User logged into system",
                    IpAddress = "N/A",
                    Timestamp = u.LastLogin ?? DateTime.UtcNow,
                    Type = "Login"
                }));

            // 🚪 ACCESS LOGS
            logs.AddRange(_context.AccessLogs.Select(a => new LogEntry
            {
                Id = a.LogId,
                Action = a.AccessResult == "granted" ? "Access Granted" : "Access Denied",
                User = "Personnel",
                Details = $"RFID: {a.RfidValid}, Face: {a.FaceVerified}",
                IpAddress = "N/A",
                Timestamp = a.Timestamp,
                Type = "Access"
            }));

            // 👁 DETECTION LOGS
            logs.AddRange(_context.DetectionLogs.Select(d => new LogEntry
            {
                Id = d.DetectionId,
                Action = d.DetectionType,
                User = "System",
                Details = $"Detected {d.DetectedCount} (Confidence: {d.Confidence})",
                IpAddress = "Camera",
                Timestamp = d.Timestamp,
                Type = "Detection"
            }));

            // 🚨 ALERTS
            logs.AddRange(_context.Alerts.Select(a => new LogEntry
            {
                Id = a.AlertId,
                Action = a.Type,
                User = "System",
                Details = $"{a.Description} (Severity: {a.Severity})",
                IpAddress = "N/A",
                Timestamp = a.Timestamp,
                Type = "Alert"
            }));

            var orderedLogs = logs
                .OrderByDescending(x => x.Timestamp)
                .ToList();

            return View(orderedLogs);
        }
    }
}