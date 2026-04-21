using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Models;
using WebApp.Data;
using System.Linq;
using System;
using System.Collections.Generic;

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

        public IActionResult Index(string type = "all")
        {
            var logs = new List<LogEntry>();

            // =========================
            // USER LOGIN LOGS
            // =========================
            if (type == "all" || type == "login")
            {
                logs.AddRange(_context.Users
                    .Where(u => u.LastLogin != null)
                    .Select(u => new LogEntry
                    {
                        Id = u.Id,
                        Action = "User Login",
                        User = u.Username,
                        Details = "User successfully logged into the system",
                        IpAddress = "N/A",
                        Timestamp = u.LastLogin ?? DateTime.UtcNow,
                        Type = "Login"
                    }));
            }

            // =========================
            // ACCESS LOGS
            // =========================
            if (type == "all" || type == "access")
            {
                logs.AddRange(_context.AccessLogs.Select(a => new LogEntry
                {
                    Id = a.LogId,
                    Action = a.AccessResult == "granted" ? "Access Granted" : "Access Denied",
                    User = "Security System",
                    Details =
                        $"RFID: {(a.RfidValid ? "Valid" : "Invalid")} | " +
                        $"Face: {(a.FaceVerified ? "Verified" : "Failed")}",
                    IpAddress = "Local Device",
                    Timestamp = a.Timestamp,
                    Type = "Access"
                }));
            }

            // =========================
            // DETECTION LOGS
            // =========================
            if (type == "all" || type == "detection")
            {
                logs.AddRange(_context.DetectionLogs.Select(d => new LogEntry
                {
                    Id = d.DetectionId,
                    Action = d.DetectionType,
                    User = "AI Monitoring System",
                    Details =
                        $"Objects Detected: {d.DetectedCount} | " +
                        $"Confidence: {d.Confidence}%",
                    IpAddress = "Camera Module",
                    Timestamp = d.Timestamp,
                    Type = "Detection"
                }));
            }

            // =========================
            // ALERT LOGS
            // =========================
            if (type == "all" || type == "alert")
            {
                logs.AddRange(_context.Alerts.Select(a => new LogEntry
                {
                    Id = a.AlertId,

                    // FIX: enum -> string
                    Action = a.Type.ToString(),

                    User = "Security System",

                    Details =
                        $"{a.Description} | Severity: {a.Severity}",

                    IpAddress = "N/A",
                    Timestamp = a.Timestamp,
                    Type = "Alert"
                }));
            }

            var orderedLogs = logs
                .OrderByDescending(x => x.Timestamp)
                .ToList();

            ViewBag.Filter = type;

            return View(orderedLogs);
        }
    }
}