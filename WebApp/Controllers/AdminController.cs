using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using SmartSecuritySystem.Models;
using WebApp.Models;
using System;
using System.Collections.Generic;
using System.Linq;

namespace WebApp.Controllers
{
    [Authorize(Roles = "Admin")]
    public class AdminController : Controller
    {
        // 🔥 In-memory users (temporary storage)
        private static List<User> users = new List<User>
        {
            new User {
                Id = 1,
                Name = "John Doe",
                Username = "johndoe",
                Email = "john.doe@securevision.com",
                Status = "Active",
                LastLogin = DateTime.Now.AddHours(-5),
                Role = "Security",
                PasswordHash = "1234"
            },
            new User {
                Id = 2,
                Name = "Jane Smith",
                Username = "janesmith",
                Email = "jane.smith@securevision.com",
                Status = "Active",
                LastLogin = DateTime.Now.AddDays(-1),
                Role = "Security",
                PasswordHash = "1234"
            }
        };

        // 🔥 System status (shared)
        private static SystemStatus systemStatus = new SystemStatus();

        // ------------------ DASHBOARD ------------------
        public IActionResult Index()
        {
            var model = new AdminDashboardViewModel
            {
                TotalPersonnel = users.Count,
                ActiveUsers = users.Count(u => u.Status == "Active"),
                InactiveUsers = users.Count(u => u.Status != "Active"),
                RecentLogins = users.Count(u =>
                    u.LastLogin.HasValue &&
                    (DateTime.Now - u.LastLogin.Value).TotalHours <= 24
                ),
                RecentPersonnel = users
                    .OrderByDescending(u => u.LastLogin ?? DateTime.MinValue)
                    .Take(5)
                    .ToList()
            };

            return View(model);
        }

        // ------------------ PERSONNEL ------------------
        public IActionResult Personnel(string? search)
        {
            IEnumerable<User> filtered = users;

            if (!string.IsNullOrWhiteSpace(search))
            {
                search = search.Trim();

                filtered = users.Where(u =>
                    (!string.IsNullOrEmpty(u.Name) && u.Name.Contains(search, StringComparison.OrdinalIgnoreCase)) ||
                    (!string.IsNullOrEmpty(u.Username) && u.Username.Contains(search, StringComparison.OrdinalIgnoreCase)) ||
                    (!string.IsNullOrEmpty(u.Email) && u.Email.Contains(search, StringComparison.OrdinalIgnoreCase))
                );
            }

            return View(filtered.ToList());
        }

        // ------------------ ADD USER ------------------
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(User user)
        {
            if (!ModelState.IsValid)
            {
                return RedirectToAction("Personnel");
            }

            user.Id = users.Any() ? users.Max(u => u.Id) + 1 : 1;
            user.Status = "Active";
            user.LastLogin = null;
            user.Role = string.IsNullOrEmpty(user.Role) ? "Security" : user.Role;

            // ⚠️ NOTE: In real apps, hash passwords!
            if (string.IsNullOrEmpty(user.PasswordHash))
            {
                user.PasswordHash = "1234"; // fallback (dev only)
            }

            users.Add(user);

            return RedirectToAction("Personnel");
        }

        // ------------------ DELETE USER ------------------
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Delete(int id)
        {
            var user = users.FirstOrDefault(u => u.Id == id);

            if (user == null)
            {
                return NotFound();
            }

            users.Remove(user);

            return RedirectToAction("Personnel");
        }

        // ------------------ SYSTEM SETTINGS ------------------
        public IActionResult System()
        {
            return View(systemStatus);
        }

        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult UpdateSetting(string setting, bool value)
        {
            if (string.IsNullOrEmpty(setting))
                return BadRequest();

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

                default:
                    return BadRequest();
            }

            return Ok(new { success = true });
        }
    }

    // ------------------ VIEWMODEL ------------------
    public class AdminDashboardViewModel
    {
        public int TotalPersonnel { get; set; }
        public int ActiveUsers { get; set; }
        public int InactiveUsers { get; set; }
        public int RecentLogins { get; set; }

        public List<User> RecentPersonnel { get; set; } = new List<User>();
    }
}