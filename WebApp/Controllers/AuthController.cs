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

        [HttpGet]
        public IActionResult Login() => View();

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

<<<<<<< Updated upstream
            var user = await _context.Users.FirstOrDefaultAsync(u => u.Username == username);
=======
            var user = await _context.Users
                .FirstOrDefaultAsync(u => u.Username == username);

>>>>>>> Stashed changes
            if (user == null)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account does not exist";
                return View("Login");
            }

<<<<<<< Updated upstream
            if (!string.Equals(user.Status?.Trim(), "Active", StringComparison.OrdinalIgnoreCase))
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account is inactive or locked";
                return View("Login");
            }

=======
            var tenMinutesAgo = now.AddMinutes(-10);
            var failedAttempts = await _context.LoginLogs
                .Where(l => l.Username == username && !l.Success && l.Timestamp >= tenMinutesAgo)
                .CountAsync();

            if (failedAttempts >= 3)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account temporarily locked. Try again after 10 minutes.";
                return View("Login");
            }

            if (!string.Equals(user.Status?.Trim(), "active", StringComparison.OrdinalIgnoreCase))
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account is inactive or locked";
                return View("Login");
            }

>>>>>>> Stashed changes
            var storedPassword = user.PasswordHash?.Trim() ?? "";
            var hashedInput = HashPassword(password?.Trim() ?? "");

            
            bool passwordMatches = string.Equals(storedPassword, password, StringComparison.Ordinal) ||
                                  string.Equals(storedPassword, hashedInput, StringComparison.Ordinal);

            if (!passwordMatches)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Invalid username or password";
                return View("Login");
            }

<<<<<<< Updated upstream
            // --- REDIRECT IF MUST CHANGE PASSWORD ---
            if (user.MustChangePassword)
            {
                TempData["ForcedChangeUserId"] = user.Id;
                return RedirectToAction("ForcedChangePassword");
            }

            await LogLogin(username, ipAddress, true);

           
            if (string.Equals(storedPassword, password, StringComparison.Ordinal))
=======
            await LogLogin(username, ipAddress, true);

            if (string.Equals(storedPassword, inputPassword, StringComparison.Ordinal))
>>>>>>> Stashed changes
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
                new Claim(ClaimTypes.Role, role)
            };

<<<<<<< Updated upstream
=======
            if (user.MustChangePassword)
            {
                claims.Add(new Claim("MustChangePassword", "true"));
            }

>>>>>>> Stashed changes
            var identity = new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme);
            await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme, new ClaimsPrincipal(identity), new AuthenticationProperties { IsPersistent = rememberMe });

<<<<<<< Updated upstream
            return role.Equals("Admin", StringComparison.OrdinalIgnoreCase) ? RedirectToAction("Index", "Admin") : RedirectToAction("Index", "Dashboard");
        }

        [HttpPost]
        public async Task<IActionResult> ForgotPassword(string email)
        {
            
=======
            await HttpContext.SignInAsync(
                CookieAuthenticationDefaults.AuthenticationScheme,
                principal,
                new AuthenticationProperties
                {
                    IsPersistent = rememberMe
                });

            // ✅ ROLE-BASED REDIRECT KUNG MUSTCHANGEPASSWORD
            if (user.MustChangePassword)
            {
                if (role.Equals("Admin", StringComparison.OrdinalIgnoreCase))
                    return RedirectToAction("ForcedChangePassword", "Auth"); // walang sidebar
                else
                    return RedirectToAction("Index", "Profile"); // may sidebar
            }

            if (role.Equals("Admin", StringComparison.OrdinalIgnoreCase))
                return RedirectToAction("Index", "Admin");

            return RedirectToAction("Index", "Dashboard");
        }

        // =========================
        // FORCED CHANGE PASSWORD (GET)
        // =========================
        [HttpGet]
        public IActionResult ForcedChangePassword()
        {
            var userId = GetUserId();
            if (userId == null) return RedirectToAction("Login");

            ViewBag.UserId = userId;
            return View("~/Views/Auth/ForcedChangePassword.cshtml");
        }

        // =========================
        // FORCED CHANGE PASSWORD (POST)
        // =========================
        [HttpPost]
        public async Task<IActionResult> ForcedChangePassword(int userId, string newPassword, string confirmPassword)
        {
            if (newPassword != confirmPassword)
            {
                ViewBag.Error = "Passwords do not match.";
                ViewBag.UserId = userId;
                return View("~/Views/Auth/ForcedChangePassword.cshtml");
            }

            if (newPassword.Length < 8)
            {
                ViewBag.Error = "Password must be at least 8 characters.";
                ViewBag.UserId = userId;
                return View("~/Views/Auth/ForcedChangePassword.cshtml");
            }

            var user = await _context.Users.FindAsync(userId);
            if (user == null) return RedirectToAction("Login");

            user.PasswordHash = HashPassword(newPassword);
            user.MustChangePassword = false;
            user.UpdatedAt = DateTime.UtcNow;

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
                new AuthenticationProperties { IsPersistent = false });

            if (role.Equals("Admin", StringComparison.OrdinalIgnoreCase))
                return RedirectToAction("Index", "Admin");

            return RedirectToAction("Index", "Dashboard");
        }

        // =========================
        // FORGOT PASSWORD
        // =========================
        [HttpPost]
        public async Task<IActionResult> ForgotPassword(string email)
        {
            ViewBag.ShowForgot = true;

>>>>>>> Stashed changes
            if (string.IsNullOrWhiteSpace(email))
            {
                ViewBag.ForgotError = "Email is required";
                return View("Login");
            }

            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == email);
            if (user == null)
            {
<<<<<<< Updated upstream
                ViewBag.ForgotError = "Email not found in our system.";
                return View("Login");
            }

            // Generate temporary password
            var newPass = GenerateRandomPassword(10);
            user.PasswordHash = HashPassword(newPass);
            user.MustChangePassword = true;
=======
                ViewBag.ForgotError = "Email not found";
                return View("Login");
            }

            var newPassword = GenerateRandomPassword(10);
            user.PasswordHash = HashPassword(newPassword);
            user.MustChangePassword = true; // ← flag para ma-redirect sa tamang page
>>>>>>> Stashed changes
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

<<<<<<< Updated upstream
            // Email details
            string subject = "SecureVision - Temporary Password";
            string body = $@"
                <h3>Password Reset Request</h3>
                <p>Hello {user.Username},</p>
                <p>You have requested a password reset for your SecureVision account.</p>
                <p>Your temporary password is: <b>{newPass}</b></p>
                <p>Please login and change your password immediately for security purposes.</p>
                <br>
                <p><i>If you did not request this, please contact your administrator.</i></p>";

            SendEmail(user.Email, subject, body);

            ViewBag.ForgotMessage = "Check your email for the temporary password.";
=======
            SendEmail(
                user.Email ?? "",
                "Your New Password — SecureVision",
                $"Hello {user.FullName},\n\nYour new temporary password is: {newPassword}\n\nPlease log in and change it immediately."
            );

            ViewBag.ForgotMessage = "A new password has been sent to your email.";
>>>>>>> Stashed changes
            return View("Login");
        }

        [HttpGet]
        public IActionResult ForcedChangePassword()
        {
            if (TempData["ForcedChangeUserId"] == null) return RedirectToAction("Login");
            ViewBag.UserId = TempData["ForcedChangeUserId"];
            return View();
        }

        [HttpPost]
        public async Task<IActionResult> ForcedChangePassword(int userId, string newPassword, string confirmPassword)
        {
<<<<<<< Updated upstream
            if (newPassword != confirmPassword)
            {
                ViewBag.Error = "Passwords do not match.";
                ViewBag.UserId = userId;
                return View();
            }

            var user = await _context.Users.FindAsync(userId);
            if (user != null)
            {
                user.PasswordHash = HashPassword(newPassword);
                user.MustChangePassword = false;
                user.UpdatedAt = DateTime.UtcNow;
                await _context.SaveChangesAsync();
                return RedirectToAction("Login");
            }
            return RedirectToAction("Login");
=======
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
>>>>>>> Stashed changes
        }

        // =========================
        // HELPERS
        // =========================
        private async Task LogLogin(string username, string ip, bool success)
        {
<<<<<<< Updated upstream
            try
=======
            var id = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            return int.TryParse(id, out var userId) ? userId : null;
        }

        private string GenerateRandomPassword(int length)
        {
            const string upper = "ABCDEFGHJKLMNPQRSTUVWXYZ";
            const string lower = "abcdefghijkmnopqrstuvwxyz";
            const string digits = "123456789";
            const string special = "!@#$%&*";
            const string all = upper + lower + digits + special;

            length = Math.Max(length, 8);
            var random = new Random();
            var password = new char[length];

            password[0] = upper[random.Next(upper.Length)];
            password[1] = lower[random.Next(lower.Length)];
            password[2] = digits[random.Next(digits.Length)];
            password[3] = special[random.Next(special.Length)];

            for (int i = 4; i < length; i++)
                password[i] = all[random.Next(all.Length)];

            for (int i = password.Length - 1; i > 0; i--)
>>>>>>> Stashed changes
            {
                _context.LoginLogs.Add(new LoginLog { Username = username, IpAddress = ip, Success = success, Timestamp = DateTime.UtcNow });
                await _context.SaveChangesAsync();
            }
            catch { /* Fail-safe */ }
        }

        private string HashPassword(string password)
        {
<<<<<<< Updated upstream
=======
            password ??= "";
>>>>>>> Stashed changes
            using var sha = SHA256.Create();
            return Convert.ToBase64String(sha.ComputeHash(Encoding.UTF8.GetBytes(password ?? "")));
        }

        private string GenerateRandomPassword(int length)
        {
            const string chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz123456789!@#$%&*";
            var random = new Random();
            return new string(Enumerable.Repeat(chars, length).Select(s => s[random.Next(s.Length)]).ToArray());
        }

        private void SendEmail(string toEmail, string subject, string body)
        {
<<<<<<< Updated upstream
            try
=======
            var fromEmail = "abuanmarden4@gmail.com";
            var appPassword = "womlpksgninuqgty";

            var client = new SmtpClient("smtp.gmail.com", 587)
>>>>>>> Stashed changes
            {
                var fromEmail = "abuanmarden4@gmail.com";
                var appPassword = "womlpksgninuqgty";

                var client = new SmtpClient("smtp.gmail.com", 587)
                {
                    EnableSsl = true,
                    Credentials = new NetworkCredential(fromEmail, appPassword)
                };

                var mail = new MailMessage
                {
                    From = new MailAddress(fromEmail, "SecureVision Admin"),
                    Subject = subject,
                    Body = body,
                    IsBodyHtml = true 
                };
                mail.To.Add(toEmail);

                client.Send(mail);
            }
            catch (Exception ex)
            {
                System.Diagnostics.Debug.WriteLine("Email Error: " + ex.Message);
            }
        }
    }
}
