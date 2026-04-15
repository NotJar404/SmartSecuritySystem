using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using SmartSecuritySystem.Models;
using WebApp.Models;
using WebApp.Data;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;

namespace SmartSecuritySystem.Controllers
{
    [Authorize] // ✅ IMPORTANT: protects all actions
    public class ProfileController : Controller
    {
        private readonly AppDbContext _context;

        public ProfileController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // GET: PROFILE
        // =========================
        [HttpGet]
        public async Task<IActionResult> Index()
        {
            var userId = GetUserId();

            var user = await _context.Users.FindAsync(userId);
            if (user == null)
                return RedirectToAction("Login", "Auth");

            var model = new Profile
            {
                Id = user.Id,
                FullName = user.FullName,
                Username = user.Username,
                Email = user.Email,
                Role = user.Role,
                ProfileImagePath = string.IsNullOrEmpty(user.ProfileImagePath)
                    ? "/images/default-profile.png"
                    : user.ProfileImagePath
            };

            return View(model);
        }

        // =========================
        // UPDATE PROFILE
        // =========================
        [HttpPost]
        public async Task<IActionResult> UpdateProfile(Profile model)
        {
            var userId = GetUserId();
            var user = await _context.Users.FindAsync(userId);

            if (user == null)
                return RedirectToAction("Login", "Auth");

            user.FullName = model.FullName;
            user.Username = model.Username;
            user.Email = model.Email;
            user.UpdatedAt = DateTime.UtcNow;

            // ✅ IMAGE UPLOAD (SAFER)
            if (model.ProfileImage != null && model.ProfileImage.Length > 0)
            {
                var uploadsFolder = Path.Combine(
                    Directory.GetCurrentDirectory(),
                    "wwwroot/images/profiles"
                );

                if (!Directory.Exists(uploadsFolder))
                    Directory.CreateDirectory(uploadsFolder);

                var extension = Path.GetExtension(model.ProfileImage.FileName);

                // 🔒 basic validation
                var allowedExtensions = new[] { ".jpg", ".jpeg", ".png" };
                if (!allowedExtensions.Contains(extension.ToLower()))
                {
                    TempData["Error"] = "Only JPG and PNG files are allowed.";
                    return RedirectToAction("Index");
                }

                var fileName = Guid.NewGuid() + extension;
                var filePath = Path.Combine(uploadsFolder, fileName);

                using var stream = new FileStream(filePath, FileMode.Create);
                await model.ProfileImage.CopyToAsync(stream);

                user.ProfileImagePath = "/images/profiles/" + fileName;
            }

            await _context.SaveChangesAsync();

            TempData["Success"] = "Profile updated successfully.";
            return RedirectToAction("Index");
        }

        // =========================
        // CHANGE PASSWORD
        // =========================
        [HttpPost]
        public async Task<IActionResult> ChangePassword(Changepass model)
        {
            var userId = GetUserId();
            var user = await _context.Users.FindAsync(userId);

            if (user == null)
                return RedirectToAction("Login", "Auth");

            if (!VerifyPassword(model.CurrentPassword, user.PasswordHash))
            {
                TempData["PasswordError"] = "Current password is incorrect.";
                return RedirectToAction("Index");
            }

            if (model.NewPassword != model.ConfirmPassword)
            {
                TempData["PasswordError"] = "Passwords do not match.";
                return RedirectToAction("Index");
            }

            if (model.NewPassword.Length < 6)
            {
                TempData["PasswordError"] = "Password must be at least 6 characters.";
                return RedirectToAction("Index");
            }

            user.PasswordHash = HashPassword(model.NewPassword);
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

            TempData["PasswordSuccess"] = "Password updated successfully.";
            return RedirectToAction("Index");
        }

        // =========================
        // CLAIM HELPER (FIXED)
        // =========================
        private int GetUserId()
        {
            var claim = User.FindFirst(ClaimTypes.NameIdentifier);
            if (claim == null)
                throw new InvalidOperationException("User ID claim not found.");
            return int.Parse(claim.Value);
        }

        // =========================
        // SECURITY HELPERS
        // =========================
        private static string HashPassword(string password)
        {
            using var sha = SHA256.Create();
            var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes(password));
            return Convert.ToBase64String(bytes);
        }

        private static bool VerifyPassword(string password, string hash)
        {
            return HashPassword(password) == hash;
        }
    }
}