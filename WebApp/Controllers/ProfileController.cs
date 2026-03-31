using Microsoft.AspNetCore.Mvc;
using WebApp.Models;  // Profile & Changepass
using WebApp.Services; // AuthService
using System.IO;

namespace SmartSecuritySystem.Controllers
{
    public class ProfileController : Controller
    {
        private readonly AuthService _authService;

        public ProfileController(AuthService authService)
        {
            _authService = authService;
        }

        // =========================
        // GET: PROFILE
        // =========================
        [HttpGet]
        public IActionResult Index()
        {
            var user = _authService.GetCurrentUser(HttpContext);
            if (user == null) return RedirectToAction("Login", "Auth");

            var model = new Profile
            {
                Id = user.Id,
                Name = user.Name,
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
        public IActionResult UpdateProfile(Profile model)
        {
            var user = _authService.GetCurrentUser(HttpContext);
            if (user == null) return RedirectToAction("Login", "Auth");

            user.Name = model.Name;
            user.Username = model.Username;

            // Handle image upload
            if (model.ProfileImage != null && model.ProfileImage.Length > 0)
            {
                var uploadsFolder = Path.Combine(Directory.GetCurrentDirectory(), "wwwroot/images/profiles");
                if (!Directory.Exists(uploadsFolder))
                    Directory.CreateDirectory(uploadsFolder);

                var fileName = Guid.NewGuid().ToString() + Path.GetExtension(model.ProfileImage.FileName);
                var filePath = Path.Combine(uploadsFolder, fileName);

                using (var stream = new FileStream(filePath, FileMode.Create))
                {
                    model.ProfileImage.CopyTo(stream);
                }

                user.ProfileImagePath = "/images/profiles/" + fileName;
            }

            TempData["Success"] = "Profile updated successfully.";
            return RedirectToAction("Index");
        }

        // =========================
        // CHANGE PASSWORD
        // =========================
        [HttpPost]
        public IActionResult ChangePassword(Changepass model)
        {
            var user = _authService.GetCurrentUser(HttpContext);
            if (user == null) return RedirectToAction("Login", "Auth");

            if (!_authService.VerifyPassword(user, model.CurrentPassword))
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

            _authService.UpdatePassword(user.Id, model.NewPassword);

            TempData["PasswordSuccess"] = "Password updated successfully.";
            return RedirectToAction("Index");
        }
    }
}