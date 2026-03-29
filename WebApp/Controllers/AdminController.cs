using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using SmartSecuritySystem.Models;
using WebApp.Models;
using System;
using System.Collections.Generic;
using System.Linq;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin")] // only Admin can access
    public class AdminController : Controller
    {
        // In-memory user list (existing)
        private static List<User> users = new List<User>
        {
            new User { Id = 1, Name = "John Doe", Username = "johndoe", Email = "john.doe@securevision.com", Status = "Active", LastLogin = DateTime.Now.AddHours(-5), Role = "Security", PasswordHash = "1234" },
            new User { Id = 2, Name = "Jane Smith", Username = "janesmith", Email = "jane.smith@securevision.com", Status = "Active", LastLogin = DateTime.Now.AddDays(-1), Role = "Security", PasswordHash = "1234" }
        };

        // In-memory system status (singleton for now)
        private static SystemStatus systemStatus = new SystemStatus();

        // ------------------ DASHBOARD ------------------
        public IActionResult Index()
        {
            var model = new AdminDashboardViewModel
            {
                TotalPersonnel = users.Count,
                ActiveUsers = users.Count(u => u.Status == "Active"),
                InactiveUsers = users.Count(u => u.Status != "Active"),
                RecentLogins = users.Count(u => u.LastLogin.HasValue && (DateTime.Now - u.LastLogin.Value).TotalHours <= 24),
                RecentPersonnel = users.OrderByDescending(u => u.LastLogin ?? DateTime.MinValue).Take(5).ToList()
            };

            return View(model);
        }

        // ------------------ PERSONNEL ------------------
        public IActionResult Personnel(string search)
        {
            var filtered = users;

            if (!string.IsNullOrEmpty(search))
            {
                filtered = users
                    .Where(u => u.Name.Contains(search, StringComparison.OrdinalIgnoreCase)
                             || u.Username.Contains(search, StringComparison.OrdinalIgnoreCase))
                    .ToList();
            }

            return View(filtered);
        }

        [HttpPost]
        public IActionResult Add(User user)
        {
            user.Id = users.Count > 0 ? users.Max(u => u.Id) + 1 : 1;
            user.Status = "Active";
            user.LastLogin = null;
            user.Role = "Security"; // default role
            users.Add(user);

            return RedirectToAction("Personnel");
        }

        public IActionResult Delete(int id)
        {
            var user = users.FirstOrDefault(u => u.Id == id);
            if (user != null)
                users.Remove(user);

            return RedirectToAction("Personnel");
        }

        // ------------------ SYSTEM SETTINGS ------------------
        public IActionResult System()
        {
            // optional: you could sync camera stats here if needed
            return View(systemStatus);
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult UpdateSetting(string setting, bool value)
        {
            switch (setting)
            {
                case "Notifications":
                    systemStatus.NotificationsEnabled = value;
                    break;
                case "Recording":
                    systemStatus.RecordingEnabled = value;
                    break;
                case "AI":
                    systemStatus.AiDetectionEnabled = value;
                    break;
            }

            return Ok();
        }
    }

    // ------------------ VIEWMODEL ------------------
    public class AdminDashboardViewModel
    {
        public int TotalPersonnel { get; set; }
        public int ActiveUsers { get; set; }
        public int InactiveUsers { get; set; }
        public int RecentLogins { get; set; }

        public List<User> RecentPersonnel { get; set; }
    }
}