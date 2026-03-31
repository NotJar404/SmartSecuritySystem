using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Models;
using System.Collections.Generic;
using System.Linq;
using System;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")]
    public class AlertsController : Controller
    {
        // TEMP DATA (Replace with DB later)
        private static List<Alert> alerts = new List<Alert>
        {
            new Alert {
                Id = 1,
                Title = "Unauthorized Person",
                Description = "Unknown person detected at main entrance",
                Location = "Front Door",
                Severity = SeverityLevel.CRITICAL,
                Status = AlertStatus.Active,
                CreatedAt = DateTime.Now.AddMinutes(-5)
            },
            new Alert {
                Id = 2,
                Title = "Motion Detected",
                Description = "Movement detected in restricted area",
                Location = "Back Yard",
                Severity = SeverityLevel.WARNING,
                Status = AlertStatus.Active,
                CreatedAt = DateTime.Now.AddMinutes(-15)
            },
            new Alert {
                Id = 3,
                Title = "Door Open",
                Description = "Garage door opened outside normal hours",
                Location = "Garage",
                Severity = SeverityLevel.WARNING,
                Status = AlertStatus.Resolved,
                CreatedAt = DateTime.Now.AddMinutes(-30)
            }
        };

        // 📋 VIEW ALERTS WITH FILTERING
        public IActionResult Index(string filter = "All")
        {
            IEnumerable<Alert> data = alerts;

            switch (filter)
            {
                case "Active":
                    data = data.Where(a => a.Status == AlertStatus.Active);
                    break;

                case "Acknowledged":
                    data = data.Where(a => a.Status == AlertStatus.Acknowledged);
                    break;

                case "Resolved":
                    data = data.Where(a => a.Status == AlertStatus.Resolved);
                    break;

                default:
                    break;
            }

            ViewBag.Filter = filter;
            return View(data.ToList());
        }

        // 🟡 ACKNOWLEDGE ALERT
        [HttpPost]
        public IActionResult Acknowledge(int id)
        {
            var alert = alerts.FirstOrDefault(a => a.Id == id);

            if (alert != null && alert.Status == AlertStatus.Active)
            {
                alert.Status = AlertStatus.Acknowledged;
            }

            return RedirectToAction("Index");
        }

        // ✅ RESOLVE ALERT
        [HttpPost]
        public IActionResult Resolve(int id)
        {
            var alert = alerts.FirstOrDefault(a => a.Id == id);

            if (alert != null)
            {
                alert.Status = AlertStatus.Resolved;
            }

            return RedirectToAction("Index");
        }

        // 🔴 ESCALATE ALERT
        [HttpPost]
        public IActionResult Escalate(int id)
        {
            var alert = alerts.FirstOrDefault(a => a.Id == id);

            if (alert != null)
            {
                // Increase severity to CRITICAL
                alert.Severity = SeverityLevel.CRITICAL;

                // Optional: if not resolved, bring back to active priority
                if (alert.Status != AlertStatus.Resolved)
                {
                    alert.Status = AlertStatus.Active;
                }
            }

            return RedirectToAction("Index");
        }
    }
}