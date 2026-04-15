using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Net;
using System.Net.Mail;
using WebApp.Data;
using SmartSecuritySystem.Models;

namespace SmartSecuritySystem.Controllers
{
    public class AuthController : Controller
    {
        private readonly AppDbContext _context;

        public AuthController(AppDbContext context)
        {
            _context = context;
        }

        // =========================
        // LOGIN (GET)
        // =========================
        [HttpGet]
        public IActionResult Login()
        {
            return View();
        }

        // =========================
        // LOGIN (POST)
        // =========================
        [HttpPost]
        public async Task<IActionResult> Login(string username, string password, bool rememberMe)
        {
            var ipAddress = HttpContext.Connection.RemoteIpAddress?.ToString() ?? "Unknown";
            var now = DateTime.UtcNow;

            if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Invalid username or password";
                return View("Login");
            }

            var user = await _context.Users
                .FirstOrDefaultAsync(u => u.Username == username);

            if (user == null)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Invalid username or password";
                return View("Login");
            }

            // ACCOUNT LOCK (3 FAILS / 10 MIN)
            var tenMinutesAgo = now.AddMinutes(-10);

            var failedAttempts = await _context.LoginLogs
                .Where(l => l.Username == username &&
                            !l.Success &&
                            l.Timestamp >= tenMinutesAgo)
                .CountAsync();

            if (failedAttempts >= 3)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account temporarily locked. Try again after 10 minutes.";
                return View("Login");
            }

            // STATUS CHECK
            if (!string.Equals(user.Status?.Trim(), "active", StringComparison.OrdinalIgnoreCase))
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account is inactive or locked";
                return View("Login");
            }

            // PASSWORD CHECK
            var stored = user.PasswordHash?.Trim() ?? "";
            var input = password?.Trim() ?? "";
            var hashedInput = HashPassword(input);

            bool passwordMatches =
                string.Equals(stored, input, StringComparison.Ordinal) ||
                string.Equals(stored, hashedInput, StringComparison.Ordinal);

            if (!passwordMatches)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Invalid username or password";
                return View("Login");
            }

            // SUCCESS LOGIN
            await LogLogin(username, ipAddress, true);

            // AUTO HASH UPGRADE
            if (string.Equals(stored, input, StringComparison.Ordinal))
            {
                user.PasswordHash = hashedInput;
                user.UpdatedAt = now;
            }

            user.LastLogin = now;
            await _context.SaveChangesAsync();

            var role = user.Role?.Trim() ?? "Security";

            var claims = new List<Claim>
            {
                new Claim(ClaimTypes.NameIdentifier, user.Id.ToString()),
                new Claim(ClaimTypes.Name, user.Username ?? ""),
                new Claim(ClaimTypes.Role, role),
                new Claim("FullName", user.FullName ?? ""),
                new Claim("Email", user.Email ?? "")
            };

            var identity = new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme);
            var principal = new ClaimsPrincipal(identity);

            await HttpContext.SignInAsync(
                CookieAuthenticationDefaults.AuthenticationScheme,
                principal,
                new AuthenticationProperties
                {
                    IsPersistent = rememberMe
                });

            if (role.Equals("Admin", StringComparison.OrdinalIgnoreCase))
                return RedirectToAction("Index", "Admin");

            return RedirectToAction("Index", "Dashboard");
        }

        // =========================
        // FORGOT PASSWORD (UPDATED FOR SINGLE PAGE)
        // =========================
        [HttpPost]
        public async Task<IActionResult> ForgotPassword(string email)
        {
            ViewBag.ShowForgot = true;

            if (string.IsNullOrWhiteSpace(email))
            {
                ViewBag.ForgotError = "Email is required";
                return View("Login");
            }

            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == email);

            if (user == null)
            {
                ViewBag.ForgotError = "Email not found";
                return View("Login");
            }

            var newPassword = GenerateRandomPassword(10);

            user.PasswordHash = HashPassword(newPassword);
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

            SendEmail(
                user.Email ?? "",
                "Your New Password",
                $"Hello {user.FullName},\n\nYour new password is: {newPassword}\n\nPlease change it after login."
            );

            ViewBag.ForgotMessage = "A new password has been sent to your email.";
            return View("Login");
        }

        // =========================
        // LOG LOGIN ATTEMPT
        // =========================
        private async Task LogLogin(string username, string ip, bool success)
        {
            var log = new LoginLog
            {
                Username = username,
                IpAddress = ip,
                Success = success,
                Timestamp = DateTime.UtcNow
            };

            _context.LoginLogs.Add(log);
            await _context.SaveChangesAsync();
        }

        // =========================
        // LOGOUT
        // =========================
        [HttpGet]
        public async Task<IActionResult> Logout()
        {
            await HttpContext.SignOutAsync();
            return RedirectToAction("Login");
        }

        // =========================
        // PROFILE
        // =========================
        [HttpGet]
        public async Task<IActionResult> Profile()
        {
            var userId = GetUserId();
            if (userId == null) return RedirectToAction("Login");

            var user = await _context.Users.FindAsync(userId);
            if (user == null) return RedirectToAction("Login");

            return View(user);
        }

        // =========================
        // UPDATE PROFILE
        // =========================
        [HttpPost]
        public async Task<IActionResult> UpdateProfile(string fullName, string email)
        {
            var userId = GetUserId();
            if (userId == null) return RedirectToAction("Login");

            var user = await _context.Users.FindAsync(userId);
            if (user == null) return RedirectToAction("Login");

            user.FullName = fullName;
            user.Email = email;
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

            TempData["Success"] = "Profile updated successfully!";
            return RedirectToAction("Profile");
        }

        // =========================
        // CHANGE PASSWORD
        // =========================
        [HttpPost]
        public async Task<IActionResult> ChangePassword(string currentPassword, string newPassword)
        {
            var userId = GetUserId();
            if (userId == null) return RedirectToAction("Login");

            var user = await _context.Users.FindAsync(userId);
            if (user == null) return RedirectToAction("Login");

            var stored = user.PasswordHash?.Trim() ?? "";
            var input = currentPassword?.Trim() ?? "";
            var hashedInput = HashPassword(input);

            bool matches =
                string.Equals(stored, input, StringComparison.Ordinal) ||
                string.Equals(stored, hashedInput, StringComparison.Ordinal);

            if (!matches)
            {
                TempData["PasswordError"] = "Current password is incorrect";
                return RedirectToAction("Profile");
            }

            user.PasswordHash = HashPassword(newPassword ?? "");
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

            TempData["PasswordSuccess"] = "Password updated successfully!";
            return RedirectToAction("Profile");
        }

        // =========================
        // HELPERS
        // =========================
        private int? GetUserId()
        {
            var id = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            return int.TryParse(id, out var userId) ? userId : null;
        }

        private string GenerateRandomPassword(int length)
        {
            const string chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz123456789";
            var random = new Random();

            return new string(Enumerable.Range(0, length)
                .Select(_ => chars[random.Next(chars.Length)]).ToArray());
        }

        private string HashPassword(string password)
        {
            password ??= "";

            using var sha = SHA256.Create();
            return Convert.ToBase64String(
                sha.ComputeHash(Encoding.UTF8.GetBytes(password))
            );
        }

#pragma warning disable SYSLIB0014
        private void SendEmail(string toEmail, string subject, string body)
        {
            var fromEmail = "yourgmail@gmail.com";
            var appPassword = "your_app_password";

            var client = new SmtpClient("smtp.gmail.com", 587)
            {
                EnableSsl = true,
                Credentials = new NetworkCredential(fromEmail, appPassword)
            };

            var mail = new MailMessage
            {
                From = new MailAddress(fromEmail),
                Subject = subject ?? "",
                Body = body ?? ""
            };

            mail.To.Add(toEmail ?? "");
            client.Send(mail);
        }
#pragma warning restore SYSLIB0014
    }
}