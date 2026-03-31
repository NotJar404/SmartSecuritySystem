using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using SmartSecuritySystem.Models;
using System;
using System.Collections.Generic;
using System.Security.Claims;
using System.Threading.Tasks;
using WebApp.Models;
using WebApp.Services;

namespace SmartSecuritySystem.Controllers
{
    public class AuthController : Controller
    {
        private readonly AuthService _authService;

        public AuthController(AuthService authService)
        {
            _authService = authService;
        }

        // =========================
        // GET: LOGIN
        // =========================
        [HttpGet]
        public IActionResult Login()
        {
            return View();
        }

        // =========================
        // POST: LOGIN
        // =========================
        [HttpPost]
        public async Task<IActionResult> Login(string username, string password, bool rememberMe)
        {
            var (success, user) = _authService.ValidateUser(username, password);

            if (!success)
            {
                ViewBag.Error = "Invalid username or password";
                return View();
            }

            // Store user ID in session
            HttpContext.Session.SetInt32("UserId", user.Id);

            var claims = new List<Claim>
            {
                new Claim(ClaimTypes.Name, user.Username),
                new Claim(ClaimTypes.Role, user.Role)
            };

            var identity = new ClaimsIdentity(
                claims,
                CookieAuthenticationDefaults.AuthenticationScheme);

            var principal = new ClaimsPrincipal(identity);

            var authProperties = new AuthenticationProperties
            {
                IsPersistent = rememberMe,
                ExpiresUtc = rememberMe
                    ? DateTime.UtcNow.AddDays(7)
                    : DateTime.UtcNow.AddHours(1)
            };

            await HttpContext.SignInAsync(
                CookieAuthenticationDefaults.AuthenticationScheme,
                principal,
                authProperties);

            // Redirect based on role
            return user.Role == "Admin"
                ? RedirectToAction("Index", "Admin")
                : RedirectToAction("Index", "Dashboard");
        }

        // =========================
        // LOGOUT
        // =========================
        [HttpGet]
        public async Task<IActionResult> Logout()
        {
            HttpContext.Session.Clear();
            await HttpContext.SignOutAsync();
            return RedirectToAction("Login");
        }

        // =========================
        // GET: PROFILE
        // =========================
        [HttpGet]
        public IActionResult Profile()
        {
            var user = _authService.GetCurrentUser(HttpContext);
            if (user == null) return RedirectToAction("Login");

            return View(user);
        }

        // =========================
        // POST: PROFILE (update name, role, picture)
        // =========================
        [HttpPost]
        public IActionResult UpdateProfile(int id, string name, string role)
        {
            var user = _authService.GetCurrentUser(HttpContext);
            if (user == null) return RedirectToAction("Login");

            user.Name = name;
            user.Role = role;

            TempData["Success"] = "Profile updated successfully!";
            return RedirectToAction("Profile");
        }

        // =========================
        // POST: CHANGE PASSWORD
        // =========================
        [HttpPost]
        public IActionResult ChangePassword(Changepass model)
        {
            var user = _authService.GetCurrentUser(HttpContext);
            if (user == null) return RedirectToAction("Login");

            // Validate model
            if (!ModelState.IsValid)
            {
                TempData["PasswordError"] = "Invalid input";
                return RedirectToAction("Profile");
            }

            // Check current password
            if (!_authService.VerifyPassword(user, model.CurrentPassword))
            {
                TempData["PasswordError"] = "Current password is incorrect";
                return RedirectToAction("Profile");
            }

            // Update password
            _authService.UpdatePassword(user.Id, model.NewPassword);

            TempData["PasswordSuccess"] = "Password updated successfully!";
            return RedirectToAction("Profile");
        }
    }
}