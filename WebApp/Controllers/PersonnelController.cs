using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.Extensions.Logging;
using System.Security.Cryptography;
using System.Text;
using WebApp.Data;
using SmartSecuritySystem.Models;
using System.Linq;
using System;
using System.Security.Claims;

namespace SmartSecuritySystem.Controllers
{
    [Authorize(Roles = "Admin")]
    public class PersonnelController : Controller
    {
        private readonly AppDbContext _context;
        private readonly ILogger<PersonnelController> _logger;

        public PersonnelController(AppDbContext context, ILogger<PersonnelController> logger)
        {
            _context = context;
            _logger = logger;
        }

        // =========================
        // VIEW
        // =========================
        public IActionResult Index(string search)
        {
            var users = _context.Users.AsQueryable();

            if (!string.IsNullOrWhiteSpace(search))
            {
                users = users.Where(u =>
                    (u.FullName ?? "").Contains(search) ||
                    (u.Username ?? "").Contains(search) ||
                    (u.Email ?? "").Contains(search));
            }

            return View("~/Views/Admin/Personnel.cshtml", users.ToList());
        }

        // =========================
        // ADD
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(User user)
        {
            _logger.LogInformation("🔥 ADD START - {Username}", user?.Username);

            ModelState.Remove("Id");

            if (user == null)
                return RedirectToAction(nameof(Index));

            // VALIDATION
            if (_context.Users.Any(u => u.Username == user.Username))
                ModelState.AddModelError("Username", "Username already exists.");

            if (_context.Users.Any(u => u.Email == user.Email))
                ModelState.AddModelError("Email", "Email already exists.");

            if (string.IsNullOrWhiteSpace(user.PasswordHash))
                ModelState.AddModelError("PasswordHash", "Password is required.");

            if (!ModelState.IsValid)
            {
                _logger.LogWarning("❌ MODELSTATE INVALID");
                return View("~/Views/Admin/Personnel.cshtml", _context.Users.ToList());
            }

            // FORCE ROLE
            user.Role = "Security";

            // NORMALIZE STATUS
            user.Status = NormalizeStatus(user.Status);

            // 🔥 FIX: HASH ONLY IF NOT HASHED
            if (!IsSha256Base64(user.PasswordHash))
            {
                user.PasswordHash = HashPassword(user.PasswordHash);
            }

            user.CreatedAt = DateTime.UtcNow;
            user.UpdatedAt = DateTime.UtcNow;

            try
            {
                _context.Users.Add(user);
                _context.SaveChanges();

                _logger.LogInformation("✅ USER CREATED: {Username}", user.Username);
            }
            catch (Exception ex)
            {
                _logger.LogError(ex, "💥 DATABASE ERROR");
                return View("~/Views/Admin/Personnel.cshtml", _context.Users.ToList());
            }

            return RedirectToAction(nameof(Index));
        }

        // =========================
        // EDIT
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Edit(User user)
        {
            var existing = _context.Users.FirstOrDefault(u => u.Id == user.Id);

            if (existing == null)
                return RedirectToAction(nameof(Index));

            if (_context.Users.Any(u => u.Username == user.Username && u.Id != user.Id))
                ModelState.AddModelError("Username", "Username already exists.");

            if (_context.Users.Any(u => u.Email == user.Email && u.Id != user.Id))
                ModelState.AddModelError("Email", "Email already exists.");

            if (!ModelState.IsValid)
                return View("~/Views/Admin/Personnel.cshtml", _context.Users.ToList());

            existing.FullName = user.FullName;
            existing.Username = user.Username;
            existing.Email = user.Email;

            existing.Role = "Security";

            // NORMALIZE STATUS
            existing.Status = NormalizeStatus(user.Status);

            existing.UpdatedAt = DateTime.UtcNow;

            // 🔥 FIX: HANDLE PASSWORD SAFELY
            if (!string.IsNullOrWhiteSpace(user.PasswordHash))
            {
                if (!IsSha256Base64(user.PasswordHash))
                    existing.PasswordHash = HashPassword(user.PasswordHash);
                else
                    existing.PasswordHash = user.PasswordHash;
            }

            _context.SaveChanges();

            _logger.LogInformation("✅ EDIT SUCCESS");

            return RedirectToAction(nameof(Index));
        }

        // =========================
        // DELETE
        // =========================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Delete(int id)
        {
            var user = _context.Users.FirstOrDefault(u => u.Id == id);

            if (user == null)
                return RedirectToAction(nameof(Index));

            if (user.Role == "Admin" || user.Id == GetCurrentUserId())
                return RedirectToAction(nameof(Index));

            _context.Users.Remove(user);
            _context.SaveChanges();

            _logger.LogInformation("🗑 DELETE SUCCESS");

            return RedirectToAction(nameof(Index));
        }

        // =========================
        // STATUS NORMALIZER
        // =========================
        private string NormalizeStatus(string status)
        {
            if (string.IsNullOrWhiteSpace(status))
                return "active";

            status = status.Trim().ToLower();

            return status switch
            {
                "active" => "active",
                "inactive" => "inactive",
                "locked" => "locked",
                _ => "active"
            };
        }

        // =========================
        // HASH PASSWORD
        // =========================
        private string HashPassword(string password)
        {
            using var sha = SHA256.Create();
            return Convert.ToBase64String(
                sha.ComputeHash(Encoding.UTF8.GetBytes(password))
            );
        }

        // =========================
        // DETECT HASH (PREVENT DOUBLE HASH)
        // =========================
        private bool IsSha256Base64(string s)
        {
            if (string.IsNullOrEmpty(s))
                return false;

            if (s.Length != 44)
                return false;

            try
            {
                var bytes = Convert.FromBase64String(s);
                return bytes.Length == 32;
            }
            catch
            {
                return false;
            }
        }

        // =========================
        // CURRENT USER (FIXED)
        // =========================
        private int GetCurrentUserId()
        {
            var userId = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            return userId != null ? Convert.ToInt32(userId) : 0;
        }
    }
}