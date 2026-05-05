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

            var user = await _context.Users.FirstOrDefaultAsync(u => u.Username == username);
            if (user == null)
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account does not exist";
                return View("Login");
            }

            if (!string.Equals(user.Status?.Trim(), "Active", StringComparison.OrdinalIgnoreCase))
            {
                await LogLogin(username, ipAddress, false);
                ViewBag.LoginError = "Account is inactive or locked";
                return View("Login");
            }

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

            // --- REDIRECT IF MUST CHANGE PASSWORD ---
            if (user.MustChangePassword)
            {
                TempData["ForcedChangeUserId"] = user.Id;
                return RedirectToAction("ForcedChangePassword");
            }

            await LogLogin(username, ipAddress, true);

           
            if (string.Equals(storedPassword, password, StringComparison.Ordinal))
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

            var identity = new ClaimsIdentity(claims, CookieAuthenticationDefaults.AuthenticationScheme);
            await HttpContext.SignInAsync(CookieAuthenticationDefaults.AuthenticationScheme, new ClaimsPrincipal(identity), new AuthenticationProperties { IsPersistent = rememberMe });

            return role.Equals("Admin", StringComparison.OrdinalIgnoreCase) ? RedirectToAction("Index", "Admin") : RedirectToAction("Index", "Dashboard");
        }

        [HttpPost]
        public async Task<IActionResult> ForgotPassword(string email)
        {
            
            if (string.IsNullOrWhiteSpace(email))
            {
                ViewBag.ForgotError = "Email is required";
                return View("Login");
            }

            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == email);
            if (user == null)
            {
                ViewBag.ForgotError = "Email not found in our system.";
                return View("Login");
            }

            // Generate temporary password
            var newPass = GenerateRandomPassword(10);
            user.PasswordHash = HashPassword(newPass);
            user.MustChangePassword = true;
            user.UpdatedAt = DateTime.UtcNow;

            await _context.SaveChangesAsync();

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
        }

        // =========================
        // HELPERS
        // =========================
        private async Task LogLogin(string username, string ip, bool success)
        {
            try
            {
                _context.LoginLogs.Add(new LoginLog { Username = username, IpAddress = ip, Success = success, Timestamp = DateTime.UtcNow });
                await _context.SaveChangesAsync();
            }
            catch { /* Fail-safe */ }
        }

        private string HashPassword(string password)
        {
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
            try
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
