using Microsoft.AspNetCore.Mvc;
using Microsoft.AspNetCore.Authorization;
using Microsoft.Extensions.Logging;
using System.Security.Cryptography;
using System.Text;
using WebApp.Data;
using SmartSecuritySystem.Models;
using SmartSecuritySystem.ViewModels;
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

        // =====================================================
        // MAIN VIEW (ONLY ENTRY POINT THAT RETURNS THE VIEW)
        // =====================================================
        public IActionResult Index(string? search)
        {
            var model = BuildViewModel(search);
            return View("~/Views/Admin/Personnel.cshtml", model);
        }

        // =====================================================
        // VIEWMODEL BUILDER (CENTRALIZED - PREVENTS TYPE ERRORS)
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
                    HasFaceData = !string.IsNullOrEmpty(m.FaceEmbedding),
                    CreatedAt = m.CreatedAt,
                    LastAccess = null
                }).ToList()
            };
        }

        // =====================================================
        // ADD (UNIFIED SAFE FLOW)
        // =====================================================
        [HttpPost]
        [ValidateAntiForgeryToken]
        public IActionResult Add(User user, string RegType, string? Department, string? RfidTag, string? Phone)
        {
            if (RegType == "staff")
                AddStaff(user);
            else
                AddCampusMember(user.FullName, user.Email, Department, RfidTag, Phone);

            return RedirectToAction(nameof(Index));
        }

        private void AddStaff(User user)
        {
            ModelState.Remove("Id");

            if (string.IsNullOrWhiteSpace(user.Username))
                return;

            // Gmail-only validation
            if (!IsValidGmailAddress(user.Email))
                return;

            if (_context.Users.Any(u => u.Username == user.Username))
                return;

            // Auto-generate secure temporary password
            var tempPassword = GenerateSecurePassword(10);

            user.Role = "Security";
            user.Status = NormalizeStatus(user.Status);
            user.PasswordHash = HashPassword(tempPassword);
            user.MustChangePassword = true;
            user.CreatedAt = DateTime.UtcNow;
            user.UpdatedAt = DateTime.UtcNow;

            _context.Users.Add(user);
            _context.SaveChanges();

            // Send credentials via email
            try
            {
                SendCredentialEmail(user.Email, user.FullName, user.Username, tempPassword);
            }
            catch (Exception ex)
            {
                _logger.LogWarning($"Failed to send credentials email: {ex.Message}");
            }
        }

        private void AddCampusMember(string? name, string? email, string? dept, string? rfid, string? phone)
        {
            if (string.IsNullOrWhiteSpace(name) || string.IsNullOrWhiteSpace(rfid))
                return;

            if (_context.AuthorizedPersonnel.Any(p => p.RfidTag == rfid))
                return;

            var member = new AuthorizedPersonnel
            {
                FullName = name,
                Email = email,
                Department = dept,
                RfidTag = rfid,
                Phone = phone,
                Status = "active",
                SecurityLevel = "normal",
                FaceEmbedding = "PENDING_ENROLLMENT",
                CreatedAt = DateTime.UtcNow,
                UpdatedAt = DateTime.UtcNow
            };

            _context.AuthorizedPersonnel.Add(member);
            _context.SaveChanges();
        }

        // =====================================================
        // EDIT (USERS ONLY - SAFE)
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
        // DELETE (USERS ONLY - SAFE GUARD)
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

        private void SendCredentialEmail(string toEmail, string fullName, string username, string tempPassword)
        {
            var fromEmail = "yourgmail@gmail.com";
            var appPassword = "your_app_password";

            var client = new System.Net.Mail.SmtpClient("smtp.gmail.com", 587)
            {
                EnableSsl = true,
                Credentials = new System.Net.NetworkCredential(fromEmail, appPassword)
            };

            var mail = new System.Net.Mail.MailMessage
            {
                From = new System.Net.Mail.MailAddress(fromEmail),
                Subject = "SecureVision — Your Account Credentials",
                Body = $"Hello {fullName},\n\n" +
                       $"Your SecureVision account has been created.\n\n" +
                       $"Username: {username}\n" +
                       $"Temporary Password: {tempPassword}\n\n" +
                       $"This password is one-time use only. You will be required to change it upon first login.\n\n" +
                       $"— SecureVision Security System"
            };

            mail.To.Add(toEmail);
            client.Send(mail);
        }
    }
}