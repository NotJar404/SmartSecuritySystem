using Microsoft.AspNetCore.Mvc;
using SmartSecuritySystem.Models;
using System;
using System.Collections.Generic;
using System.Linq;
using WebApp.Models;

namespace WebApp.Controllers
{
    public class AdminController : Controller
    {
        // In-memory user list (replace with DB in production)
        private static List<User> users = new List<User>
        {
            new User
            {
                Id = 1,
                Name = "John Doe",
                Username = "johndoe",
                Email = "john.doe@securevision.com",
                Status = "Active",
                LastLogin = DateTime.Now.AddHours(-5),
                Role = "Security",
                PasswordHash = "1234"
            },
            new User
            {
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

        // Admin Dashboard view (existing)
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

        // Personnel Management Page
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

        // Add Personnel POST
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

        // Delete Personnel
        public IActionResult Delete(int id)
        {
            var user = users.FirstOrDefault(u => u.Id == id);
            if (user != null)
                users.Remove(user);

            return RedirectToAction("Personnel");
        }
    }

    // ViewModel (you can move this to Models/AdminDashboardViewModel.cs later)
    public class AdminDashboardViewModel
    {
        public int TotalPersonnel { get; set; }
        public int ActiveUsers { get; set; }
        public int InactiveUsers { get; set; }
        public int RecentLogins { get; set; }

        public List<User> RecentPersonnel { get; set; }
    }
}