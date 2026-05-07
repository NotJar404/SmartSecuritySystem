using Microsoft.AspNetCore.Authentication;
using Microsoft.AspNetCore.Authentication.Cookies;
using Microsoft.AspNetCore.Mvc;
using Microsoft.EntityFrameworkCore;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Net;
using System.Net.Mail;
using WebApp.Data;
using SmartSecuritySystem.Models;

namespace SmartSecuritySystem.Controllers
{
    public class AuthController : Controller
    {
        private readonly AppDbContext _context;
        private readonly IConfiguration _configuration;

        public AuthController(AppDbContext context, IConfiguration configuration)
        {
            _context = context;
            _configuration = configuration;
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
        // FORGOT PASSWORD — STEP 1: SEND OTP
        // =========================
        [HttpPost]
        public async Task<IActionResult> ForgotPassword(string email)
        {
            ViewBag.ShowForgot = true;

            // Validate email input
            if (string.IsNullOrWhiteSpace(email))
            {
                ViewBag.ForgotError = "Email is required";
                return View("Login");
            }

            // Check if the email exists in the database
            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == email);

            if (user == null)
            {
                ViewBag.ForgotError = "Email not found";
                return View("Login");
            }

            // Generate 6-digit OTP
            var otp = GenerateOtp();

            // Store OTP in session with expiry (5 minutes)
            HttpContext.Session.SetString("OTP_Code", otp);
            HttpContext.Session.SetString("OTP_Email", email);
            HttpContext.Session.SetString("OTP_Expiry", DateTime.UtcNow.AddMinutes(5).ToString("o"));
            HttpContext.Session.SetInt32("OTP_Attempts", 0);

            // Send OTP via email
            try
            {
                SendOtpEmail(user.Email ?? "", user.FullName ?? "User", otp);
                ViewBag.ShowOtp = true;
                ViewBag.OtpEmail = email;
                ViewBag.ForgotMessage = "A 6-digit verification code has been sent to your email.";
            }
            catch (Exception ex)
            {
                ViewBag.ForgotError = $"Failed to send email: {ex.Message}";
            }

            return View("Login");
        }

        // =========================
        // FORGOT PASSWORD — STEP 2: VERIFY OTP
        // =========================
        [HttpPost]
        public IActionResult VerifyOtp(string otpCode)
        {
            ViewBag.ShowForgot = true;

            var sessionOtp = HttpContext.Session.GetString("OTP_Code");
            var sessionEmail = HttpContext.Session.GetString("OTP_Email");
            var sessionExpiry = HttpContext.Session.GetString("OTP_Expiry");
            var attempts = HttpContext.Session.GetInt32("OTP_Attempts") ?? 0;

            // Validate session data exists
            if (string.IsNullOrEmpty(sessionOtp) || string.IsNullOrEmpty(sessionEmail) || string.IsNullOrEmpty(sessionExpiry))
            {
                ViewBag.ForgotError = "Session expired. Please request a new verification code.";
                return View("Login");
            }

            // Check max attempts (3)
            if (attempts >= 3)
            {
                HttpContext.Session.Remove("OTP_Code");
                HttpContext.Session.Remove("OTP_Email");
                HttpContext.Session.Remove("OTP_Expiry");
                HttpContext.Session.Remove("OTP_Attempts");
                ViewBag.ForgotError = "Too many failed attempts. Please request a new code.";
                return View("Login");
            }

            // Check expiry
            if (DateTime.TryParse(sessionExpiry, out var expiry) && DateTime.UtcNow > expiry)
            {
                HttpContext.Session.Remove("OTP_Code");
                HttpContext.Session.Remove("OTP_Email");
                HttpContext.Session.Remove("OTP_Expiry");
                HttpContext.Session.Remove("OTP_Attempts");
                ViewBag.ForgotError = "Verification code has expired. Please request a new one.";
                return View("Login");
            }

            // Validate OTP
            if (!string.Equals(otpCode?.Trim(), sessionOtp, StringComparison.Ordinal))
            {
                HttpContext.Session.SetInt32("OTP_Attempts", attempts + 1);
                ViewBag.ShowOtp = true;
                ViewBag.OtpEmail = sessionEmail;
                ViewBag.OtpError = $"Invalid code. {2 - attempts} attempt(s) remaining.";
                return View("Login");
            }

            // OTP verified — show password reset fields
            ViewBag.ShowResetFields = true;
            ViewBag.ResetEmail = sessionEmail;
            ViewBag.OtpVerified = true;

            return View("Login");
        }

        // =========================
        // FORGOT PASSWORD — STEP 3: RESET PASSWORD
        // =========================
        [HttpPost]
        public async Task<IActionResult> ResetPassword(string resetEmail, string newPassword, string confirmPassword)
        {
            ViewBag.ShowForgot = true;

            var sessionEmail = HttpContext.Session.GetString("OTP_Email");

            // Verify session integrity
            if (string.IsNullOrEmpty(sessionEmail) || !string.Equals(resetEmail, sessionEmail, StringComparison.OrdinalIgnoreCase))
            {
                ViewBag.ForgotError = "Session expired. Please restart the password reset process.";
                return View("Login");
            }

            // Validate passwords
            if (string.IsNullOrWhiteSpace(newPassword) || string.IsNullOrWhiteSpace(confirmPassword))
            {
                ViewBag.ShowResetFields = true;
                ViewBag.ResetEmail = sessionEmail;
                ViewBag.ResetError = "Both password fields are required.";
                return View("Login");
            }

            if (!string.Equals(newPassword, confirmPassword, StringComparison.Ordinal))
            {
                ViewBag.ShowResetFields = true;
                ViewBag.ResetEmail = sessionEmail;
                ViewBag.ResetError = "Passwords do not match.";
                return View("Login");
            }

            // Enforce password complexity: min 8 chars, uppercase, lowercase, digit, special
            if (!IsPasswordComplex(newPassword))
            {
                ViewBag.ShowResetFields = true;
                ViewBag.ResetEmail = sessionEmail;
                ViewBag.ResetError = "Password must be at least 8 characters and include uppercase, lowercase, number, and special character.";
                return View("Login");
            }

            // Find user and update password
            var user = await _context.Users.FirstOrDefaultAsync(u => u.Email == sessionEmail);
            if (user == null)
            {
                ViewBag.ForgotError = "Account not found. Please try again.";
                return View("Login");
            }

            user.PasswordHash = HashPassword(newPassword);
            user.MustChangePassword = false;
            user.UpdatedAt = DateTime.UtcNow;
            await _context.SaveChangesAsync();

            // Clear all OTP session data
            HttpContext.Session.Remove("OTP_Code");
            HttpContext.Session.Remove("OTP_Email");
            HttpContext.Session.Remove("OTP_Expiry");
            HttpContext.Session.Remove("OTP_Attempts");

            // Send confirmation email
            try
            {
                SendPasswordChangedEmail(user.Email ?? "", user.FullName ?? "User");
            }
            catch { /* Non-critical */ }

            ViewBag.LoginSuccess = "Password reset successfully! Please sign in with your new password.";
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

        private string GenerateOtp()
        {
            using var rng = RandomNumberGenerator.Create();
            var bytes = new byte[4];
            rng.GetBytes(bytes);
            var number = BitConverter.ToUInt32(bytes, 0) % 900000 + 100000;
            return number.ToString();
        }

        private bool IsPasswordComplex(string password)
        {
            if (string.IsNullOrWhiteSpace(password) || password.Length < 8)
                return false;

            bool hasUpper = Regex.IsMatch(password, @"[A-Z]");
            bool hasLower = Regex.IsMatch(password, @"[a-z]");
            bool hasDigit = Regex.IsMatch(password, @"[0-9]");
            bool hasSpecial = Regex.IsMatch(password, @"[!@#$%^&*()_+\-=\[\]{};':""\\|,.<>\/?]");

            return hasUpper && hasLower && hasDigit && hasSpecial;
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

        // =========================
        // EMAIL HELPERS
        // =========================
#pragma warning disable SYSLIB0014
        private void SendOtpEmail(string toEmail, string fullName, string otp)
        {
            var subject = "SecureVision — Password Reset Verification Code";
            var body = BuildHtmlEmail(
                fullName,
                "Password Reset Verification",
                $@"<p style=""margin:0 0 16px 0;color:#4a4540;font-size:15px;line-height:1.6;"">
                    You have requested to reset your password. Please use the following verification code to proceed:
                </p>
                <div style=""text-align:center;margin:24px 0;"">
                    <div style=""display:inline-block;background:linear-gradient(135deg,#D4A373,#BC8F62);color:#ffffff;font-size:32px;font-weight:700;letter-spacing:12px;padding:16px 32px;border-radius:12px;font-family:'Courier New',monospace;"">
                        {otp}
                    </div>
                </div>
                <p style=""margin:0 0 8px 0;color:#4a4540;font-size:14px;line-height:1.6;"">
                    This code will expire in <strong>5 minutes</strong>. Do not share this code with anyone.
                </p>
                <p style=""margin:0 0 16px 0;color:#6B635B;font-size:13px;line-height:1.6;"">
                    If you did not request this password reset, please ignore this email or contact your system administrator immediately.
                </p>"
            );

            SendEmail(toEmail, subject, body);
        }

        private void SendPasswordChangedEmail(string toEmail, string fullName)
        {
            var subject = "SecureVision — Password Changed Successfully";
            var body = BuildHtmlEmail(
                fullName,
                "Password Changed",
                $@"<p style=""margin:0 0 16px 0;color:#4a4540;font-size:15px;line-height:1.6;"">
                    Your SecureVision account password has been successfully changed.
                </p>
                <div style=""background:#f0f9f4;border:1px solid #c3e6cb;border-radius:8px;padding:16px;margin:16px 0;"">
                    <p style=""margin:0;color:#2D7A56;font-size:14px;"">
                        <strong>✓ Password updated</strong> on {DateTime.UtcNow:MMMM dd, yyyy} at {DateTime.UtcNow:hh:mm tt} UTC
                    </p>
                </div>
                <p style=""margin:0 0 16px 0;color:#6B635B;font-size:13px;line-height:1.6;"">
                    If you did not make this change, please contact your system administrator immediately to secure your account.
                </p>"
            );

            SendEmail(toEmail, subject, body);
        }

        public void SendCredentialEmail(string toEmail, string fullName, string username, string tempPassword)
        {
            var subject = "SecureVision — Your Account Credentials";
            var body = BuildHtmlEmail(
                fullName,
                "Welcome to SecureVision",
                $@"<p style=""margin:0 0 16px 0;color:#4a4540;font-size:15px;line-height:1.6;"">
                    Your SecureVision security system account has been created. Please use the credentials below to sign in:
                </p>
                <div style=""background:#FAF7F2;border:1px solid #E2DCD5;border-radius:8px;padding:20px;margin:16px 0;"">
                    <table style=""width:100%;border-collapse:collapse;"">
                        <tr>
                            <td style=""padding:8px 0;color:#6B635B;font-size:13px;font-weight:600;width:120px;"">Username</td>
                            <td style=""padding:8px 0;color:#2C2724;font-size:14px;font-weight:700;"">{username}</td>
                        </tr>
                        <tr>
                            <td style=""padding:8px 0;color:#6B635B;font-size:13px;font-weight:600;"">Temporary Password</td>
                            <td style=""padding:8px 0;color:#2C2724;font-size:14px;font-family:'Courier New',monospace;font-weight:700;"">{tempPassword}</td>
                        </tr>
                    </table>
                </div>
                <p style=""margin:0 0 8px 0;color:#E07A5F;font-size:13px;font-weight:600;line-height:1.6;"">
                    ⚠ You will be required to change your password upon first login.
                </p>
                <p style=""margin:0 0 16px 0;color:#6B635B;font-size:13px;line-height:1.6;"">
                    Keep your credentials secure and do not share them with anyone.
                </p>"
            );

            SendEmail(toEmail, subject, body);
        }

        private string BuildHtmlEmail(string recipientName, string heading, string contentHtml)
        {
            return $@"<!DOCTYPE html>
<html lang=""en"">
<head>
    <meta charset=""UTF-8"">
    <meta name=""viewport"" content=""width=device-width, initial-scale=1.0"">
    <meta http-equiv=""X-UA-Compatible"" content=""IE=edge"">
    <title>{heading} — SecureVision</title>
</head>
<body style=""margin:0;padding:0;background-color:#f5f0eb;font-family:'Segoe UI','Helvetica Neue',Arial,sans-serif;"">
    <table role=""presentation"" cellpadding=""0"" cellspacing=""0"" width=""100%"" style=""background-color:#f5f0eb;"">
        <tr>
            <td align=""center"" style=""padding:40px 20px;"">
                <table role=""presentation"" cellpadding=""0"" cellspacing=""0"" width=""560"" style=""max-width:560px;width:100%;"">
                    <!-- Header -->
                    <tr>
                        <td style=""background:linear-gradient(135deg,#D4A373,#BC8F62);padding:28px 32px;border-radius:12px 12px 0 0;text-align:center;"">
                            <div style=""width:48px;height:48px;border-radius:50%;background:rgba(255,255,255,0.2);display:inline-block;line-height:48px;font-size:18px;font-weight:700;color:#ffffff;margin-bottom:12px;"">QCU</div>
                            <h1 style=""margin:8px 0 0 0;color:#ffffff;font-size:22px;font-weight:700;"">{heading}</h1>
                            <p style=""margin:4px 0 0 0;color:rgba(255,255,255,0.85);font-size:13px;"">SecureVision Security System</p>
                        </td>
                    </tr>
                    <!-- Body -->
                    <tr>
                        <td style=""background:#ffffff;padding:32px;border-left:1px solid #E2DCD5;border-right:1px solid #E2DCD5;"">
                            <p style=""margin:0 0 20px 0;color:#2C2724;font-size:16px;font-weight:600;"">
                                Hello {recipientName},
                            </p>
                            {contentHtml}
                        </td>
                    </tr>
                    <!-- Footer -->
                    <tr>
                        <td style=""background:#FAF7F2;padding:20px 32px;border-radius:0 0 12px 12px;border:1px solid #E2DCD5;border-top:none;text-align:center;"">
                            <p style=""margin:0 0 4px 0;color:#8E847B;font-size:12px;"">
                                This is an automated message from SecureVision — Quezon City University
                            </p>
                            <p style=""margin:0;color:#8E847B;font-size:11px;"">
                                AI-Assisted Smart Security & Intruder Detection System &bull; Do not reply to this email
                            </p>
                        </td>
                    </tr>
                </table>
            </td>
        </tr>
    </table>
</body>
</html>";
        }

        private void SendEmail(string toEmail, string subject, string htmlBody)
        {
            var smtpSettings = _configuration.GetSection("SmtpSettings");
            var fromEmail = smtpSettings["SenderEmail"] ?? "yourgmail@gmail.com";
            var senderName = smtpSettings["SenderName"] ?? "SecureVision Security System";
            var appPassword = smtpSettings["AppPassword"] ?? "your_app_password";
            var host = smtpSettings["Host"] ?? "smtp.gmail.com";
            var port = int.TryParse(smtpSettings["Port"], out var p) ? p : 587;
            var enableSsl = bool.TryParse(smtpSettings["EnableSsl"], out var ssl) ? ssl : true;

            var client = new SmtpClient(host, port)
            {
                EnableSsl = enableSsl,
                Credentials = new NetworkCredential(fromEmail, appPassword),
                DeliveryMethod = SmtpDeliveryMethod.Network,
                Timeout = 15000
            };

            var mail = new MailMessage
            {
                From = new MailAddress(fromEmail, senderName),
                Subject = subject ?? "",
                Body = htmlBody ?? "",
                IsBodyHtml = true,
                SubjectEncoding = Encoding.UTF8,
                BodyEncoding = Encoding.UTF8
            };

            // Add headers for better deliverability
            mail.Headers.Add("X-Mailer", "SecureVision-Mailer");
            mail.Headers.Add("X-Priority", "3");
            mail.Headers.Add("Precedence", "bulk");

            mail.To.Add(new MailAddress(toEmail));
            client.Send(mail);
        }
#pragma warning restore SYSLIB0014
    }
}