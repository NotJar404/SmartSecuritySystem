using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Models;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")] // 🔥 ADD THIS
    public class AlertsController : Controller
    {
        // TEMP: Fake data (replace with DB later)
        private static List<Alert> alerts = new List<Alert>
        {
            new Alert {
                Id = 1,
                Title = "Unauthorized Person",
                Description = "Unknown person detected at main entrance",
                Location = "Front Door",
                Severity = "CRITICAL",
                Status = "Active",
                CreatedAt = DateTime.Now.AddMinutes(-5)
            },
            new Alert {
                Id = 2,
                Title = "Motion Detected",
                Description = "Movement detected in restricted area",
                Location = "Back Yard",
                Severity = "WARNING",
                Status = "Active",
                CreatedAt = DateTime.Now.AddMinutes(-15)
            },
            new Alert {
                Id = 3,
                Title = "Door Open",
                Description = "Garage door opened outside normal hours",
                Location = "Garage",
                Severity = "WARNING",
                Status = "Resolved",
                CreatedAt = DateTime.Now.AddMinutes(-30)
            }
        };

        public IActionResult Index(string filter = "All")
        {
            var data = alerts.AsEnumerable();

            if (filter == "Active")
                data = data.Where(a => a.Status == "Active");

            if (filter == "Resolved")
                data = data.Where(a => a.Status == "Resolved");

            ViewBag.Filter = filter;

            return View(data.ToList());
        }

        [HttpPost]
        public IActionResult Resolve(int id)
        {
            var alert = alerts.FirstOrDefault(a => a.Id == id);

            if (alert != null)
                alert.Status = "Resolved";

            return RedirectToAction("Index");
        }
    }
}