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

            // Check for empty username or password
            if (string.IsNullOrWhiteSpace(username) || string.IsNullOrWhiteSpace(password))
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Invalid username or password"; // Error message
                return View("Login");
            }

            // Look for the user in the database
            var user = await _context.Users
                .FirstOrDefaultAsync(u => u.Username == username);

            // Check if the user exists
            if (user == null)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account does not exist"; // Specific error for non-existing account
                return View("Login");
            }

            // Check for failed login attempts in the last 10 minutes
            var tenMinutesAgo = now.AddMinutes(-10);
            var failedAttempts = await _context.LoginLogs
                .Where(l => l.Username == username && !l.Success && l.Timestamp >= tenMinutesAgo)
                .CountAsync();

            if (failedAttempts >= 3)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account temporarily locked. Try again after 10 minutes."; // Lock message
                return View("Login");
            }

            // Check if the account is active
            if (!string.Equals(user.Status?.Trim(), "active", StringComparison.OrdinalIgnoreCase))
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account is inactive or locked"; // Account status message
                return View("Login");
            }

            // Validate the password
            var storedPassword = user.PasswordHash?.Trim() ?? "";
            var inputPassword = password?.Trim() ?? "";
            var hashedInput = HashPassword(inputPassword);

            bool passwordMatches =
                string.Equals(storedPassword, inputPassword, StringComparison.Ordinal) ||
                string.Equals(storedPassword, hashedInput, StringComparison.Ordinal);

            if (!passwordMatches)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Invalid username or password"; // Password mismatch message
                return View("Login");
            }

            // If login is successful
            await LogLogin(username, ipAddress, true);

            // Auto hash password upgrade if it's in plain text
            if (string.Equals(storedPassword, inputPassword, StringComparison.Ordinal))
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

            // Flag for forced password change on first login
            if (user.MustChangePassword)
            {
                claims.Add(new Claim("MustChangePassword", "true"));
            }

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

            // Validate email input
            if (string.IsNullOrWhiteSpace(email))
            {
                ViewBag.ForgotError = "Email is required"; // Error message for missing email
                return View("Login");
            }

            // Check if the email exists in the database
            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == email);

            if (user == null)
            {
                ViewBag.ForgotError = "Email not found"; // Error message for non-existing email
                return View("Login");
            }

            // Generate a random password and update the user's password
            var newPassword = GenerateRandomPassword(10);
            user.PasswordHash = HashPassword(newPassword);
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

            // Send the new password to the user's email
            SendEmail(
                user.Email ?? "",
                "Your New Password",
                $"Hello {user.FullName},\n\nYour new password is: {newPassword}\n\nPlease change it after login."
            );

            ViewBag.ForgotMessage = "A new password has been sent to your email."; // Success message
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

            TempData["Success"] = "Profile updated successfully!"; // Success message
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
                TempData["PasswordError"] = "Current password is incorrect"; // Error message
                return RedirectToAction("Profile");
            }

            user.PasswordHash = HashPassword(newPassword ?? "");
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

            TempData["PasswordSuccess"] = "Password updated successfully!"; // Success message
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
            // Guarantee at least: 1 uppercase, 1 lowercase, 1 digit, 1 special char
            const string upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
            const string lower = "abcdefghijkmnopqrstuvwxyz";
            const string digits = "123456789";
            const string special = "!@#$%&*";
            const string all = upper + lower + digits + special;

            length = Math.Max(length, 8);
            var random = new Random();
            var password = new char[length];

            // Ensure one of each category
            password[0] = upper[random.Next(upper.Length)];
            password[1] = lower[random.Next(lower.Length)];
            password[2] = digits[random.Next(digits.Length)];
            password[3] = special[random.Next(special.Length)];

            // Fill rest randomly
            for (int i = 4; i < length; i++)
                password[i] = all[random.Next(all.Length)];

            // Shuffle
            for (int i = password.Length - 1; i > 0; i--)
            {
                int j = random.Next(i + 1);
                (password[i], password[j]) = (password[j], password[i]);
            }

            return new string(password);
        }

        private bool IsValidGmailAddress(string? email)
        {
            if (string.IsNullOrWhiteSpace(email)) return false;
            return email.Trim().EndsWith("@gmail.com", StringComparison.OrdinalIgnoreCase);
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