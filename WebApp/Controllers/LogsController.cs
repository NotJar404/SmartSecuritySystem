using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using WebApp.Models;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin,Security")] // 🔥 ADD THIS
    public class LogsController : Controller
    {
        private static List<LogEntry> logs = new List<LogEntry>
        {
            new LogEntry {
                Id = 1,
                Action = "User Login",
                User = "John Doe",
                Details = "Logged into system",
                IpAddress = "192.168.1.100",
                Timestamp = DateTime.Now.AddMinutes(-5)
            },
            new LogEntry {
                Id = 2,
                Action = "Camera Added",
                User = "Admin",
                Details = "Added Front Door Camera",
                IpAddress = "192.168.1.101",
                Timestamp = DateTime.Now.AddMinutes(-20)
            },
            new LogEntry {
                Id = 3,
                Action = "Alert Resolved",
                User = "John Doe",
                Details = "Resolved Unauthorized Person alert",
                IpAddress = "192.168.1.102",
                Timestamp = DateTime.Now.AddMinutes(-40)
            }
        };

        public IActionResult Index()
        {
            return View(logs.OrderByDescending(x => x.Timestamp).ToList());
        }
    }
}