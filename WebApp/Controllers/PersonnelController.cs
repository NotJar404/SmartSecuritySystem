using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.Extensions.Logging;
using System.Security.Cryptography;
using System.Text;
using System.Net;
using System.Net.Mail;
using WebApp.Data;
using WebApp.Models; // ✅ FIXED (important)
using SmartSecuritySystem.Models;
using SmartSecuritySystem.ViewModels;
using System.Linq;
using System;
using System.Security.Claims;
using System.Collections.Generic;
using Microsoft.EntityFrameworkCore;

namespace SmartSecuritySystem.Controllers
{
    [Authorize(Roles = "Admin")]
    public class PersonnelController : Controller
    {
        private readonly AppDbContext _context;
        private readonly ILogger<PersonnelController> _logger;
        private readonly IConfiguration _configuration;

        public PersonnelController(AppDbContext context, ILogger<PersonnelController> logger, IConfiguration configuration)
        {
            _context = context;
            _logger = logger;
            _configuration = configuration;
        }

        // =====================================================
        // MAIN VIEW
        // =====================================================
        public IActionResult Index(string? search)
        {
            var model = BuildViewModel(search);
            return View("~/Views/Admin/Personnel.cshtml", model);
        }

        // =====================================================
        // VIEWMODEL BUILDER
        // =====================================================
        private PersonnelManagementViewModel BuildViewModel(string? search)
        {
            var users = _context.Users.AsQueryable();
            var members = _context.AuthorizedPersonnel.AsQueryable();

            if (!string.IsNullOrWhiteSpace(search))
            {
                users = users.Where(u =>
                    (u.FullName ?? "").Contains(search) ||
                    (u.Username ?? "").Contains(search) ||
                    (u.Email ?? "").Contains(search));

                members = members.Where(m =>
                    (m.FullName ?? "").Contains(search) ||
                    (m.Email ?? "").Contains(search) ||
                    (m.Department ?? "").Contains(search));
            }

            return new PersonnelManagementViewModel
            {
                SystemUsers = users.ToList(),

                CampusMembers = members.ToList().Select(m => new AuthorizedMember
                {
                    Id = m.PersonId,
                    FullName = m.FullName,
                    Email = m.Email ?? "",
                    Phone = m.Phone ?? "",
                    Department = m.Department ?? "",
                    RfidTag = m.RfidTag ?? "",
                    Status = m.Status,
                    SecurityLevel = m.SecurityLevel,
                    HasFaceData = !string.IsNullOrEmpty(m.FaceEmbedding) && m.FaceEmbedding != "PENDING_ENROLLMENT",
                    ProfileImagePath = m.ProfileImagePath,
                    CreatedAt = m.CreatedAt,
                    LastAccess = null,
                    RoomCount = _context.PersonRoomAccess.Count(pra => pra.PersonId == m.PersonId)
                }).ToList()
            };
        }

        // =====================================================
        // ADD (UNIFIED FLOW)
        // =====================================================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(User user, string RegType, string? Department, string? RfidTag, string? Phone, IFormFile? ProfileImage)
        {
            if (RegType == "staff")
                AddStaff(user);
            else
                AddCampusMember(user.FullName, user.Email, Department, RfidTag, Phone, ProfileImage);

            return RedirectToAction(nameof(Index));
        }

        private void AddStaff(User user)
        {
            ModelState.Remove("Id");

            if (string.IsNullOrWhiteSpace(user.Username))
                return;

            if (!IsValidGmailAddress(user.Email))
                return;

            if (_context.Users.Any(u => u.Username == user.Username))
                return;

            var tempPassword = GenerateSecurePassword(10);

            user.Role = "Security";
            user.Status = NormalizeStatus(user.Status);
            user.PasswordHash = HashPassword(tempPassword);
            user.MustChangePassword = true;
            user.CreatedAt = DateTime.UtcNow;
            user.UpdatedAt = DateTime.UtcNow;

            _context.Users.Add(user);
            _context.SaveChanges();

            try
            {
                SendCredentialEmail(user.Email, user.FullName, user.Username, tempPassword);
                TempData["Success"] = $"Staff account created and credentials sent to {user.Email}";
            }
            catch (Exception ex)
            {
                _logger.LogWarning($"Failed to send credentials email: {ex.Message}");
                TempData["Error"] = $"Account created but email failed: {ex.Message}. Please configure SMTP in appsettings.json.";
            }
        }

        private void AddCampusMember(string? name, string? email, string? dept, string? rfid, string? phone, IFormFile? profileImage)
        {
            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(rfid))
                return;

            if (_context.AuthorizedPersonnel.Any(p => p.RfidTag == rfid))
                return;

            // Convert uploaded photo to base64 for face_embedded column
            string faceData = "PENDING_ENROLLMENT";
            string? profileImagePath = null;
            if (profileImage != null && profileImage.Length > 0)
            {
                try
                {
                    using var ms = new System.IO.MemoryStream();
                    profileImage.CopyTo(ms);
                    faceData = Convert.ToBase64String(ms.ToArray());
                    profileImagePath = $"data:{profileImage.ContentType};base64,{faceData}";
                }
                catch (Exception ex)
                {
                    _logger.LogWarning($"Failed to process profile image: {ex.Message}");
                }
            }

            var member = new AuthorizedPersonnel
            {
                FullName = name,
                Email = email,
                Department = dept,
                RfidTag = rfid,
                Phone = phone,
                Status = "active",
                SecurityLevel = "normal",
                FaceEmbedding = faceData,
                ProfileImagePath = profileImagePath,
                CreatedAt = DateTime.UtcNow,
                UpdatedAt = DateTime.UtcNow
            };

            _context.AuthorizedPersonnel.Add(member);
            _context.SaveChanges();

            if (faceData == "PENDING_ENROLLMENT")
                TempData["Warning"] = $"\"{name}\" has been registered but has NO face photo. " +
                                      $"Face verification will fail until a photo is uploaded. " +
                                      $"Click edit to upload a profile image.";
            else
                TempData["Success"] = $"\"{name}\" registered successfully with face photo. Don't forget to assign room access.";
        }

        // =====================================================
        // EDIT USERS (SYSTEM OPERATORS)
        // =====================================================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Edit(User user)
        {
            var existing = _context.Users.FirstOrDefault(u => u.Id == user.Id);
            if (existing == null)
                return RedirectToAction(nameof(Index));

            existing.FullName = user.FullName;
            existing.Username = user.Username;
            existing.Email = user.Email;
            existing.Status = NormalizeStatus(user.Status);
            existing.UpdatedAt = DateTime.UtcNow;

            if (!string.IsNullOrWhiteSpace(user.PasswordHash))
            {
                existing.PasswordHash = IsSha256Base64(user.PasswordHash)
                    ? user.PasswordHash
                    : HashPassword(user.PasswordHash);
            }

            _context.SaveChanges();
            return RedirectToAction(nameof(Index));
        }

        // =====================================================
        // EDIT MEMBER (AUTHORIZED PERSONNEL / CAMPUS MEMBERS)
        // =====================================================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult EditMember(int personId, string fullName, string? email, string? department, string? rfidTag, string? phone, IFormFile? ProfileImage)
        {
            var existing = _context.AuthorizedPersonnel.FirstOrDefault(p => p.PersonId == personId);
            if (existing == null)
                return RedirectToAction(nameof(Index));

            existing.FullName = fullName ?? existing.FullName;
            existing.Email = email;
            existing.Department = department;
            existing.Phone = phone;
            existing.UpdatedAt = DateTime.UtcNow;

            // Only update RFID if provided and not already taken by another member
            if (!string.IsNullOrWhiteSpace(rfidTag) && rfidTag != existing.RfidTag)
            {
                if (!_context.AuthorizedPersonnel.Any(p => p.RfidTag == rfidTag && p.PersonId != personId))
                {
                    existing.RfidTag = rfidTag;
                }
            }

            // Update face photo if a new one was uploaded
            if (ProfileImage != null && ProfileImage.Length > 0)
            {
                try
                {
                    using var ms = new System.IO.MemoryStream();
                    ProfileImage.CopyTo(ms);
                    var base64 = Convert.ToBase64String(ms.ToArray());
                    existing.FaceEmbedding = base64;
                    existing.ProfileImagePath = $"data:{ProfileImage.ContentType};base64,{base64}";
                    TempData["Success"] = $"\"{fullName}\" updated with new face photo.";
                }
                catch (Exception ex)
                {
                    _logger.LogWarning($"Failed to update profile image: {ex.Message}");
                }
            }

            _context.SaveChanges();
            return RedirectToAction(nameof(Index));
        }

        // =====================================================
        // DELETE USERS (SYSTEM OPERATORS)
        // =====================================================
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

            return RedirectToAction(nameof(Index));
        }

        // =====================================================
        // DELETE MEMBER (AUTHORIZED PERSONNEL / CAMPUS MEMBERS)
        // =====================================================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult DeleteMember(int id)
        {
            var member = _context.AuthorizedPersonnel.FirstOrDefault(p => p.PersonId == id);

            if (member == null)
                return RedirectToAction(nameof(Index));

            _context.AuthorizedPersonnel.Remove(member);
            _context.SaveChanges();

            return RedirectToAction(nameof(Index));
        }

        // =====================================================
        // HELPERS
        // =====================================================
        private string NormalizeStatus(string? status)
        {
            if (string.IsNullOrWhiteSpace(status))
                return "active";

            status = status.Trim().ToLower();

            return status switch
            {
                "active" => "active",
                "inactive" => "inactive",
                "blocked" => "blocked",
                _ => "active"
            };
        }

        private string HashPassword(string password)
        {
            using var sha = SHA256.Create();
            return Convert.ToBase64String(
                sha.ComputeHash(Encoding.UTF8.GetBytes(password))
            );
        }

        private bool IsSha256Base64(string? s)
        {
            if (string.IsNullOrEmpty(s) || s.Length != 44)
                return false;

            try
            {
                return Convert.FromBase64String(s).Length == 32;
            }
            catch
            {
                return false;
            }
        }

        private int GetCurrentUserId()
        {
            var userId = User.FindFirst(ClaimTypes.NameIdentifier)?.Value;
            return userId != null ? Convert.ToInt32(userId) : 0;
        }

        private string GenerateSecurePassword(int length)
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

        // =====================================================
        // EMAIL HELPERS (SHARED HTML TEMPLATE)
        // =====================================================
#pragma warning disable SYSLIB0014
        private void SendCredentialEmail(string toEmail, string fullName, string username, string tempPassword)
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
                            <td style=""padding:8px 0;color:#6B635B;font-size:13px;font-weight:600;width:140px;"">Username</td>
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