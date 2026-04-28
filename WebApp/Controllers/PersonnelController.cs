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

            if (string.IsNullOrWhiteSpace(user.Username) || string.IsNullOrWhiteSpace(user.PasswordHash))
                return;

            if (_context.Users.Any(u => u.Username == user.Username))
                return;

            user.Role = "Security";
            user.Status = NormalizeStatus(user.Status);

            if (!IsSha256Base64(user.PasswordHash))
                user.PasswordHash = HashPassword(user.PasswordHash);

            user.CreatedAt = DateTime.UtcNow;
            user.UpdatedAt = DateTime.UtcNow;

            _context.Users.Add(user);
            _context.SaveChanges();
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
    }
}